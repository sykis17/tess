"""Unit tests for scripts/ops_three_way_demo.py (no live cloud calls)."""

from __future__ import annotations

import pytest

import scripts.ops_three_way_demo as demo


def test_resolve_standby_aws() -> None:
    provider_id, script = demo.resolve_standby("aws")
    assert provider_id == "prov_aws"
    assert script.name == "aws_standby.py"
    assert script.is_file()


def test_resolve_standby_gcp_case_insensitive() -> None:
    provider_id, script = demo.resolve_standby("GCP")
    assert provider_id == "prov_gcp"
    assert script.name == "gcp_standby.py"


def test_resolve_standby_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown standby"):
        demo.resolve_standby("azure")


def test_print_runbook_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert demo.main(["--print-runbook"]) == 0
    out = capsys.readouterr().out
    assert "/ops-status/" in out
    assert "prov_aws" in out
    assert "prov_gcp" in out
    assert "self-report" in out.lower() or "Scoring source of truth" in out


def test_print_runbook_aws_only(capsys: pytest.CaptureFixture[str]) -> None:
    assert demo.main(["--print-runbook", "aws"]) == 0
    out = capsys.readouterr().out
    assert "prov_aws" in out
    assert "Path: aws" in out
    assert "Path: gcp" not in out


def test_help_exits_two() -> None:
    assert demo.main([]) == 2
    assert demo.main(["--help"]) == 2


def test_run_demo_sequences_wake_smoke_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_standby(script: object, cmd: str) -> int:
        calls.append(("standby", str(script), cmd))
        return 0

    def fake_smoke(provider_id: str) -> int:
        calls.append(("smoke", provider_id))
        return 0

    monkeypatch.setattr(demo, "_run_standby_cmd", fake_standby)
    monkeypatch.setattr(demo, "_run_smoke", fake_smoke)
    monkeypatch.setattr(demo, "print_runbook", lambda **_: None)

    assert demo.run_demo("aws", guided=False) == 0
    assert calls[0][0] == "standby" and calls[0][2] == "wake"
    assert calls[1] == ("smoke", "prov_aws")
    assert calls[2][0] == "standby" and calls[2][2] == "sleep"


def test_run_demo_sleeps_even_when_smoke_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_standby(_script: object, cmd: str) -> int:
        calls.append(cmd)
        return 0

    monkeypatch.setattr(demo, "_run_standby_cmd", fake_standby)
    monkeypatch.setattr(demo, "_run_smoke", lambda _pid: 1)
    monkeypatch.setattr(demo, "print_runbook", lambda **_: None)

    assert demo.run_demo("gcp", guided=False) == 1
    assert calls == ["wake", "sleep"]


def test_guided_pauses(monkeypatch: pytest.MonkeyPatch) -> None:
    pauses: list[str] = []

    monkeypatch.setattr(demo, "_run_standby_cmd", lambda *_a, **_k: 0)
    monkeypatch.setattr(demo, "_run_smoke", lambda *_a, **_k: 0)
    monkeypatch.setattr(demo, "print_runbook", lambda **_: None)
    monkeypatch.setattr(demo, "_pause", lambda msg: pauses.append(msg))

    assert demo.run_demo("aws", guided=True) == 0
    assert len(pauses) == 3
    assert "ops-status" in pauses[1]


def test_main_invalid_standby() -> None:
    assert demo.main(["azure"]) == 2


def test_main_delegates_to_run_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(key: str, *, guided: bool = False) -> int:
        seen["key"] = key
        seen["guided"] = guided
        return 0

    monkeypatch.setattr(demo, "run_demo", fake_run)
    assert demo.main(["gcp", "--guided"]) == 0
    assert seen == {"key": "gcp", "guided": True}


def test_control_plane_base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_SMOKE_BASE_URL", "http://example.test/")
    assert demo.control_plane_base() == "http://example.test"
