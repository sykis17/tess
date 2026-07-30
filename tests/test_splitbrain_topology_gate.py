"""Topology gating + tally assertion for the split-brain harness (W1.5 re-sync).

The offline stack runs a single ``etcd`` service, so ``s11`` (kill the etcd Raft
leader, expect durable writes to resume on a surviving quorum member) cannot apply
there — with no survivor, sustained 503s are the *correct* behavior. The gate must
be topology-keyed, never blanket: a 3-node config still executes s11. And the
verifier's expected tally (``--expect-pass 10 --expect-skip 1``) must be enforced as
an exit-code artifact that actually fails on drift — a vacuous gate here is exactly
how the offline chain rotted invisibly before. These tests prove both at unit
level, without docker.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.ops_cp_splitbrain import __main__ as cli
from scripts.ops_cp_splitbrain.config import load_config
from scripts.ops_cp_splitbrain.harness import ScenarioResult
from scripts.ops_cp_splitbrain.scenarios import s11_kill_etcd_leader_storm as s11


def _cfg(monkeypatch, etcd_services: str):
    monkeypatch.setenv("OPS_HA_ETCD_SERVICES", etcd_services)
    return load_config()


def test_s11_skips_on_single_node_topology(monkeypatch):
    reason = s11.skip_reason(_cfg(monkeypatch, "etcd"))
    assert reason is not None
    assert "topology" in reason
    assert "quorum" in reason


def test_s11_skips_on_two_node_topology(monkeypatch):
    # 2/2 -> 1/2 after a leader kill is also quorum loss; the gate keys on <3, not ==1.
    assert s11.skip_reason(_cfg(monkeypatch, "etcd-1,etcd-2")) is not None


def test_s11_executes_on_three_node_topology(monkeypatch):
    # The dev default: the gate must NOT skip here — non-vacuity of topology keying.
    assert s11.skip_reason(_cfg(monkeypatch, "etcd-1,etcd-2,etcd-3")) is None


# --- tally assertion (--expect-pass / --expect-skip) ---------------------------------


def _result(sid: str, *, passed: bool = False, skipped: bool = False) -> ScenarioResult:
    detail = "PASS" if passed else ("SKIP: topology: quorum-only" if skipped else "FAIL: boom")
    return ScenarioResult(sid, sid, passed, detail, 0.0, skipped)


def test_check_expectations_match_is_zero():
    results = [_result(f"s{i:02}", passed=True) for i in range(10)]
    results.append(_result("s11", skipped=True))
    assert cli._check_expectations(results, 10, 1) == 0


def test_check_expectations_no_expectation_is_noop():
    results = [_result("s01", passed=True), _result("s02")]
    assert cli._check_expectations(results, None, None) == 0


def test_check_expectations_fails_on_wrong_pass_count():
    results = [_result(f"s{i:02}", passed=True) for i in range(9)]
    results.append(_result("s11", skipped=True))
    assert cli._check_expectations(results, 10, 1) == 1


def test_check_expectations_fails_on_wrong_skip_count():
    # A blanket-skip regression (extra skips) must fail even if nothing FAILed.
    results = [_result(f"s{i:02}", passed=True) for i in range(9)]
    results += [_result("s10", skipped=True), _result("s11", skipped=True)]
    assert cli._check_expectations(results, 9, 1) == 1


# --- end-to-end flag wiring: argparse -> run-all -> exit code, no docker -------------


def _fake_suite(monkeypatch, *, skip_s11: bool):
    """Two applicable scenarios + s11; run_scenario patched so no docker is touched."""

    def _mod(sid, reason=None):
        mod = SimpleNamespace(ID=sid, TITLE=sid, run=lambda ctx: None)
        if reason is not None:
            mod.skip_reason = lambda cfg: reason
        return mod

    mods = [
        _mod("s01"),
        _mod("s02"),
        _mod("s11", reason="topology: quorum-only" if skip_s11 else None),
    ]
    executed: list[str] = []

    def _fake_run(sid, title, fn, cfg=None):
        executed.append(sid)
        return _result(sid, passed=True)

    monkeypatch.setattr(cli, "ORDER", [m.ID for m in mods])
    monkeypatch.setattr(cli, "SCENARIOS", {m.ID: m for m in mods})
    monkeypatch.setattr(cli, "run_scenario", _fake_run)
    return executed


def test_run_all_expect_flags_pass_through_to_exit_code(monkeypatch):
    executed = _fake_suite(monkeypatch, skip_s11=True)
    assert cli.main(["run-all", "--expect-pass", "2", "--expect-skip", "1"]) == 0
    # The skip was decided before run_scenario — the skipped module never executed.
    assert executed == ["s01", "s02"]


def test_run_all_expect_mismatch_exits_nonzero(monkeypatch):
    _fake_suite(monkeypatch, skip_s11=True)
    # Same green run, wrong baseline: the tally gate alone must flip the exit code.
    assert cli.main(["run-all", "--expect-pass", "3", "--expect-skip", "0"]) == 1


def test_run_all_without_flags_keeps_plain_exit_semantics(monkeypatch):
    executed = _fake_suite(monkeypatch, skip_s11=False)
    assert cli.main(["run-all"]) == 0
    assert executed == ["s01", "s02", "s11"]


# --- fault-driver selection (P2 Step 5a) ---------------------------------------------
#
# OPS_HA_DRIVER picks the fault-injection backend. Selection is validated in
# load_config() — the earliest point, before any docker call — so a typo fails the run
# instead of silently driving local docker while the operator believes it is driving the
# cluster. Seam guards live in tests/test_splitbrain_driver_seam.py.


def test_unknown_driver_value_raises(monkeypatch):
    # The load-bearing one: an unrecognized value must fail closed, never fall back.
    monkeypatch.setenv("OPS_HA_DRIVER", "banana")
    with pytest.raises(ValueError, match="banana"):
        load_config()


def test_remote_driver_name_resolves_but_construction_refuses(monkeypatch):
    # `remote` is a documented value, so rejecting the NAME would make `local|remote` a
    # lie; constructing it must still refuse loudly until Step 5b lands the driver.
    from scripts.ops_cp_splitbrain.drivers import get_driver

    monkeypatch.setenv("OPS_HA_DRIVER", "remote")
    cfg = load_config()
    assert cfg.driver_name == "remote"
    with pytest.raises(NotImplementedError, match="5b"):
        get_driver(cfg)


@pytest.mark.parametrize("value", [None, "", "  ", "LOCAL"])
def test_absent_or_empty_driver_folds_to_local(monkeypatch, value):
    # verify-egress-blocked.sh uses the `-e VAR=` empty-clear idiom for its harness env;
    # an empty OPS_HA_DRIVER must mean "default", not "fail the certification chain".
    from scripts.ops_cp_splitbrain.drivers import get_driver
    from scripts.ops_cp_splitbrain.drivers.local import LocalComposeDriver

    if value is None:
        monkeypatch.delenv("OPS_HA_DRIVER", raising=False)
    else:
        monkeypatch.setenv("OPS_HA_DRIVER", value)
    cfg = load_config()
    assert cfg.driver_name == "local"
    assert isinstance(get_driver(cfg), LocalComposeDriver)
