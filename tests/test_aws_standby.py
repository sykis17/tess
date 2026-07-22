"""Unit tests for scripts/aws_standby.py (mocked AWS + HTTP)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

import scripts.aws_standby as standby


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(standby, "OPS_AWS_BASE_URL", "")
    monkeypatch.setattr(standby, "OPS_SMOKE_BASE_URL", "https://cp.example")
    monkeypatch.setattr(standby, "OPS_ADMIN_TOKEN", "test-token")
    monkeypatch.setattr(standby, "AWS_BUDGET_NAME", "")
    monkeypatch.setattr(standby, "AWS_BUDGET_ALERT_THRESHOLD", 0.80)


def test_check_budget_aborts_near_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(standby, "AWS_BUDGET_NAME", "tess-monthly")

    sts = MagicMock()
    sts.get_caller_identity.return_value = {"Account": "123456789012"}
    budgets = MagicMock()
    budgets.describe_budget.return_value = {
        "Budget": {
            "CalculatedSpend": {"ActualSpend": {"Amount": "8.50"}},
            "BudgetLimit": {"Amount": "10.00"},
        }
    }

    with (
        patch.object(standby, "_sts_client", return_value=sts),
        patch.object(standby, "_budgets_client", return_value=budgets),
    ):
        with pytest.raises(standby.BudgetExceededError, match="85.0%"):
            standby.check_budget(required=True)


def test_check_budget_passes_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(standby, "AWS_BUDGET_NAME", "tess-monthly")

    sts = MagicMock()
    sts.get_caller_identity.return_value = {"Account": "123456789012"}
    budgets = MagicMock()
    budgets.describe_budget.return_value = {
        "Budget": {
            "CalculatedSpend": {"ActualSpend": {"Amount": "5.00"}},
            "BudgetLimit": {"Amount": "10.00"},
        }
    }

    with (
        patch.object(standby, "_sts_client", return_value=sts),
        patch.object(standby, "_budgets_client", return_value=budgets),
    ):
        standby.check_budget(required=True)


def test_resolve_host_prefers_ops_aws_base_url_when_ip_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(standby, "OPS_AWS_BASE_URL", "http://54.1.2.3")
    base_url, needs_update = standby.resolve_host("54.1.2.3")
    assert base_url == "http://54.1.2.3"
    assert needs_update is False


def test_resolve_host_flags_drift_when_ip_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(standby, "OPS_AWS_BASE_URL", "http://54.1.2.3")
    base_url, needs_update = standby.resolve_host("18.191.224.191")
    assert base_url == "http://18.191.224.191"
    assert needs_update is True


def test_update_ops_provider_base_url_patches_control_plane() -> None:
    with patch("scripts.aws_standby.httpx.Client") as client_cls:
        client = MagicMock()
        client_cls.return_value.__enter__.return_value = client
        response = MagicMock()
        response.raise_for_status.return_value = None
        client.patch.return_value = response

        standby.update_ops_provider_base_url("http://18.191.224.191")

        client.patch.assert_called_once_with(
            "https://cp.example/ops/providers/prov_aws",
            headers={"Authorization": "Bearer test-token"},
            json={"base_url": "http://18.191.224.191"},
        )


def test_cycle_always_sleeps_even_when_smoke_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(standby, "AWS_BUDGET_NAME", "tess-monthly")

    with (
        patch.object(standby, "check_budget"),
        patch.object(standby, "wake", return_value="http://54.1.2.3"),
        patch.object(standby, "wait_healthy"),
        patch.object(standby, "refresh_ops_provider"),
        patch.object(standby, "run_smoke", return_value=1),
        patch.object(standby, "sleep") as sleep_mock,
    ):
        code = standby.cycle()

    assert code == 1
    sleep_mock.assert_called_once()


def test_cycle_returns_zero_on_smoke_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(standby, "AWS_BUDGET_NAME", "tess-monthly")

    with (
        patch.object(standby, "check_budget"),
        patch.object(standby, "wake", return_value="http://54.1.2.3"),
        patch.object(standby, "wait_healthy"),
        patch.object(standby, "refresh_ops_provider"),
        patch.object(standby, "run_smoke", return_value=0),
        patch.object(standby, "sleep"),
    ):
        assert standby.cycle() == 0


def test_wait_healthy_succeeds_on_ok_response() -> None:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"status": "ok", "redis": "ok"}

    with patch("scripts.aws_standby.httpx.Client") as client_cls:
        client = MagicMock()
        client_cls.return_value.__enter__.return_value = client
        client.get.return_value = response

        standby.wait_healthy("http://54.1.2.3", timeout_s=5)

        client.get.assert_called_with("http://54.1.2.3/health")


def test_wake_starts_stopped_instance() -> None:
    ec2 = MagicMock()
    ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "State": {"Name": "stopped"},
                        "PublicIpAddress": "54.1.2.3",
                    }
                ]
            }
        ]
    }
    waiter = MagicMock()
    ec2.get_waiter.return_value = waiter

    with patch.object(standby, "_ec2_client", return_value=ec2):
        base_url = standby.wake(skip_budget=True)

    ec2.start_instances.assert_called_once_with(InstanceIds=[standby.INSTANCE_ID])
    waiter.wait.assert_called_once()
    assert base_url == "http://54.1.2.3"


def test_sleep_is_idempotent_when_already_stopped() -> None:
    ec2 = MagicMock()
    ec2.describe_instances.return_value = {
        "Reservations": [{"Instances": [{"State": {"Name": "stopped"}}]}]
    }

    with patch.object(standby, "_ec2_client", return_value=ec2):
        standby.sleep()

    ec2.stop_instances.assert_not_called()


def _instance_describe(
    state: str,
    *,
    public_ip: str | None = "18.227.172.81",
) -> dict:
    instance: dict = {"State": {"Name": state}}
    if public_ip is not None:
        instance["PublicIpAddress"] = public_ip
        instance["NetworkInterfaces"] = [
            {"Association": {"PublicIp": public_ip}}
        ]
    return {"Reservations": [{"Instances": [instance]}]}


@pytest.mark.parametrize(
    ("state", "expected_code"),
    [
        ("stopped", 0),
        ("stopping", 0),
        ("running", 1),
        ("pending", 1),
    ],
)
def test_drift_check_exit_codes(state: str, expected_code: int) -> None:
    ec2 = MagicMock()
    ec2.describe_instances.return_value = _instance_describe(state)

    with patch.object(standby, "_ec2_client", return_value=ec2):
        code = standby.drift_check(allow_running=False)

    assert code == expected_code
    ec2.stop_instances.assert_not_called()
    ec2.start_instances.assert_not_called()


def test_drift_check_allow_running_skips_fail() -> None:
    ec2 = MagicMock()
    ec2.describe_instances.return_value = _instance_describe("running")

    with patch.object(standby, "_ec2_client", return_value=ec2):
        assert standby.drift_check(allow_running=True) == 0

    ec2.stop_instances.assert_not_called()


def test_drift_check_allow_running_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(standby, "AWS_STANDBY_ALLOW_RUNNING", True)
    ec2 = MagicMock()
    ec2.describe_instances.return_value = _instance_describe("pending")

    with patch.object(standby, "_ec2_client", return_value=ec2):
        assert standby.drift_check() == 0


def test_main_drift_check_dispatches() -> None:
    with patch.object(standby, "drift_check", return_value=0) as drift_mock:
        assert standby.main(["drift-check"]) == 0
    drift_mock.assert_called_once_with()


def test_main_status_alias_dispatches() -> None:
    with patch.object(standby, "drift_check", return_value=1) as drift_mock:
        assert standby.main(["status"]) == 1
    drift_mock.assert_called_once_with()


def test_preflight_ssh_sg_reminder_prints_ip(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("scripts.aws_standby.httpx.Client") as client_cls:
        client = MagicMock()
        client_cls.return_value.__enter__.return_value = client
        response = MagicMock()
        response.status_code = 200
        response.text = "203.0.113.9\n"
        client.get.return_value = response
        standby.preflight_ssh_sg_reminder()

    out = capsys.readouterr().out
    assert "203.0.113.9" in out
    assert "launch-wizard-1" in out


def test_wake_calls_ssh_preflight() -> None:
    ec2 = MagicMock()
    ec2.describe_instances.return_value = _instance_describe("running")
    with (
        patch.object(standby, "check_budget"),
        patch.object(standby, "preflight_ssh_sg_reminder") as pre,
        patch.object(standby, "_ec2_client", return_value=ec2),
        patch.object(standby, "_describe_public_ip", return_value="18.227.172.81"),
        patch.object(standby, "resolve_host", return_value=("http://18.227.172.81", False)),
    ):
        standby.wake(skip_budget=True)
    pre.assert_called_once()
