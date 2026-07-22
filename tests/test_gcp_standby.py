"""Unit tests for scripts/gcp_standby.py (mocked Compute API + HTTP)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import scripts.gcp_standby as standby


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(standby, "OPS_GCP_BASE_URL", "")
    monkeypatch.setattr(standby, "OPS_SMOKE_BASE_URL", "https://cp.example")
    monkeypatch.setattr(standby, "OPS_ADMIN_TOKEN", "test-token")
    monkeypatch.setattr(standby, "PROJECT_ID", "tess-503119")
    monkeypatch.setattr(standby, "ZONE", "us-central1-a")
    monkeypatch.setattr(standby, "INSTANCE_NAME", "tess-gcp-primary")


def _instance(status: str, *, nat_ip: str | None = "34.46.222.191") -> dict:
    body: dict = {"status": status, "name": "tess-gcp-primary"}
    if nat_ip is not None:
        body["networkInterfaces"] = [
            {"accessConfigs": [{"natIP": nat_ip, "type": "ONE_TO_ONE_NAT"}]}
        ]
    else:
        body["networkInterfaces"] = [{}]
    return body


def test_resolve_host_prefers_ops_gcp_base_url_when_ip_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(standby, "OPS_GCP_BASE_URL", "http://34.46.222.191")
    base_url, needs_update = standby.resolve_host("34.46.222.191")
    assert base_url == "http://34.46.222.191"
    assert needs_update is False


def test_resolve_host_flags_drift_when_ip_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(standby, "OPS_GCP_BASE_URL", "http://34.46.222.191")
    base_url, needs_update = standby.resolve_host("35.1.2.3")
    assert base_url == "http://35.1.2.3"
    assert needs_update is True


def test_update_ops_provider_base_url_patches_control_plane() -> None:
    with patch("scripts.gcp_standby.httpx.Client") as client_cls:
        client = MagicMock()
        client_cls.return_value.__enter__.return_value = client
        response = MagicMock()
        response.raise_for_status.return_value = None
        client.patch.return_value = response

        standby.update_ops_provider_base_url("http://35.1.2.3")

        client.patch.assert_called_once_with(
            "https://cp.example/ops/providers/prov_gcp",
            headers={"Authorization": "Bearer test-token"},
            json={"base_url": "http://35.1.2.3"},
        )


def test_cycle_always_sleeps_even_when_smoke_fails() -> None:
    with (
        patch.object(standby, "wake", return_value="http://34.46.222.191"),
        patch.object(standby, "wait_healthy"),
        patch.object(standby, "refresh_ops_provider"),
        patch.object(standby, "run_smoke", return_value=1),
        patch.object(standby, "sleep") as sleep_mock,
    ):
        code = standby.cycle()

    assert code == 1
    sleep_mock.assert_called_once()


def test_cycle_returns_zero_on_smoke_pass() -> None:
    with (
        patch.object(standby, "wake", return_value="http://34.46.222.191"),
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

    with patch("scripts.gcp_standby.httpx.Client") as client_cls:
        client = MagicMock()
        client_cls.return_value.__enter__.return_value = client
        client.get.return_value = response

        standby.wait_healthy("http://34.46.222.191", timeout_s=5)

        client.get.assert_called_with("http://34.46.222.191/health")


def test_wake_starts_terminated_instance() -> None:
    session = MagicMock()
    describe_responses = [
        _instance("TERMINATED", nat_ip=None),
        _instance("RUNNING"),
    ]
    with (
        patch.object(standby, "_authorized_session", return_value=session),
        patch.object(standby, "_describe_instance", side_effect=describe_responses),
        patch.object(standby, "_post_instance_action") as post_mock,
        patch.object(
            standby,
            "_wait_for_status",
            return_value=_instance("RUNNING"),
        ),
    ):
        base_url = standby.wake()

    post_mock.assert_called_once_with("start", session)
    assert base_url == "http://34.46.222.191"


def test_sleep_is_idempotent_when_already_terminated() -> None:
    session = MagicMock()
    with (
        patch.object(standby, "_authorized_session", return_value=session),
        patch.object(
            standby, "_describe_instance", return_value=_instance("TERMINATED")
        ),
        patch.object(standby, "_post_instance_action") as post_mock,
    ):
        standby.sleep()

    post_mock.assert_not_called()


def test_sleep_stops_running_instance() -> None:
    session = MagicMock()
    with (
        patch.object(standby, "_authorized_session", return_value=session),
        patch.object(standby, "_describe_instance", return_value=_instance("RUNNING")),
        patch.object(standby, "_post_instance_action") as post_mock,
        patch.object(standby, "_wait_for_status", return_value=_instance("TERMINATED")),
    ):
        standby.sleep()

    post_mock.assert_called_once_with("stop", session)


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [
        ("TERMINATED", 0),
        ("STOPPING", 0),
        ("RUNNING", 1),
        ("STAGING", 1),
        ("PROVISIONING", 1),
    ],
)
def test_drift_check_exit_codes(status: str, expected_code: int) -> None:
    with patch.object(standby, "_describe_instance", return_value=_instance(status)):
        code = standby.drift_check(allow_running=False)

    assert code == expected_code


def test_drift_check_allow_running_skips_fail() -> None:
    with patch.object(standby, "_describe_instance", return_value=_instance("RUNNING")):
        assert standby.drift_check(allow_running=True) == 0


def test_drift_check_allow_running_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(standby, "GCP_STANDBY_ALLOW_RUNNING", True)
    with patch.object(
        standby, "_describe_instance", return_value=_instance("STAGING")
    ):
        assert standby.drift_check() == 0


def test_main_drift_check_dispatches() -> None:
    with patch.object(standby, "drift_check", return_value=0) as drift_mock:
        assert standby.main(["drift-check"]) == 0
    drift_mock.assert_called_once_with()


def test_post_instance_action_surfaces_service_account_user_hint() -> None:
    session = MagicMock()
    response = MagicMock()
    response.status_code = 403
    response.text = "Required 'iam.serviceAccounts.actAs' permission on serviceAccountUser"
    session.post.return_value = response

    with pytest.raises(RuntimeError, match="serviceAccountUser"):
        standby._post_instance_action("start", session)


def test_preflight_adc_ok_when_gac_file_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
    capsys: pytest.CaptureFixture[str],
) -> None:
    key = tmp_path / "sa.json"
    key.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(key))
    standby.preflight_adc()
    assert str(key) in capsys.readouterr().out


def test_preflight_adc_raises_when_gac_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "GOOGLE_APPLICATION_CREDENTIALS",
        r"C:\Users\jesse\.ssh\missing-tess-gcp-ops-key.json",
    )
    with pytest.raises(RuntimeError, match="missing"):
        standby.preflight_adc()
