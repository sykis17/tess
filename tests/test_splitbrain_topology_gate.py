"""Topology gating for the split-brain harness (W1.5 offline-verifier re-sync).

The offline stack runs a single ``etcd`` service, so ``s11`` (kill the etcd Raft
leader, expect durable writes to resume on a surviving quorum member) cannot apply
there — with no survivor, sustained 503s are the *correct* behavior. The gate must
be topology-keyed, never blanket: a 3-node config still executes s11. These tests
prove that at unit level, without docker.
"""

from __future__ import annotations

from scripts.ops_cp_splitbrain.config import load_config
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
