"""Cardinality-discipline + safety guards for ops observability (Step 3).

Mirrors the static guards in ``tests/test_ops_fencing.py``: it turns the "metric labels
must be bounded" rule into a permanent CI tripwire, and asserts the ``record_*`` helpers
never raise (a metrics failure must never perturb the fenced control path).
"""

from __future__ import annotations

import pytest

from app.ops import metrics
from app.ops.models import ProviderType

pytestmark = pytest.mark.skipif(
    not metrics._PROM_AVAILABLE, reason="prometheus_client not installed"
)

# The ONLY label names any ops metric may use. Every one is a fixed code enum or a
# per-process constant. Adding a new label requires adding it here on purpose.
ALLOWED_LABELS = {
    "instance_id", "transition", "reason", "kind", "surface", "result",
    "op", "outcome", "route", "provider_type", "source", "mode", "task",
}

# Anything that is (or can become) unbounded — banned as a metric label value forever.
# (These are fine as span attributes, which are not aggregated; never as metric labels.)
BANNED_LABELS = {
    "provider_id", "session_id", "url", "path", "error", "last_error",
    "event_type", "provider", "message", "trace_id", "request_id",
}


def test_all_metrics_are_tess_ops_prefixed():
    assert metrics.ALL_METRICS, "no metrics registered"
    for m in metrics.ALL_METRICS:
        assert m._name.startswith("tess_ops_"), m._name


def test_every_label_is_allowlisted_and_not_banned():
    for m in metrics.ALL_METRICS:
        for label in m._labelnames:
            assert label in ALLOWED_LABELS, f"{m._name}: unexpected label {label!r}"
            assert label not in BANNED_LABELS, f"{m._name}: BANNED label {label!r}"


def test_no_metric_uses_provider_id():
    # The unbounded-uuid footgun this whole step exists to prevent.
    for m in metrics.ALL_METRICS:
        assert "provider_id" not in m._labelnames, m._name


def test_provider_type_label_domain_matches_enum():
    # The bounded stand-in for the banned provider_id label.
    assert {t.value for t in ProviderType} == {"hetzner", "aws", "gcp", "customer"}


def _exercise_all_recorders() -> None:
    metrics.record_role_transition("promote", "election_won")
    metrics.set_primary(True)
    metrics.set_primary(False)
    metrics.set_fence_term(7)
    metrics.set_fence_term(None)
    metrics.record_fence_reject("not_primary", "http_gate")
    metrics.record_lease_keepalive("ok")
    metrics.set_lease_ttl(10)
    metrics.record_cas("persist", "reject")
    metrics.record_mutation("fenced_503", "/ops/probe", 0.01)
    metrics.record_probe("aws", "healthy", "worker_task", 0.02)
    metrics.record_failover("switched", "active_only")
    metrics.record_worker_task("probe", "success")


def test_recorders_never_raise_when_disabled(monkeypatch):
    monkeypatch.setattr(metrics, "_METRICS_ON", False)
    _exercise_all_recorders()  # must not raise


def test_recorders_never_raise_when_enabled(monkeypatch):
    monkeypatch.setattr(metrics, "_METRICS_ON", True)
    _exercise_all_recorders()  # must not raise


def test_fence_error_kind_maps_subclasses():
    from app.ops.fencing import FenceCasError, NotPrimaryError, PersistError

    assert metrics.fence_error_kind(NotPrimaryError()) == "not_primary"
    assert metrics.fence_error_kind(FenceCasError()) == "cas_stale"
    assert metrics.fence_error_kind(PersistError()) == "persist_error"


def test_ops_task_observed_reraises_not_primary(monkeypatch):
    monkeypatch.setattr(metrics, "_METRICS_ON", True)
    from app.ops.fencing import NotPrimaryError

    @metrics.ops_task_observed("probe")
    def boom():
        raise NotPrimaryError("nope")

    with pytest.raises(NotPrimaryError):
        boom()


def test_ops_task_observed_passes_return_value(monkeypatch):
    monkeypatch.setattr(metrics, "_METRICS_ON", True)

    @metrics.ops_task_observed("probe")
    def ok():
        return 42

    assert ok() == 42


def test_classify_outcome_bounded():
    # fenced flag wins; then 2xx/auth/other. Never leaks a raw status into a label.
    assert metrics._classify_outcome(503, fenced=True) == "fenced_503"
    assert metrics._classify_outcome(200, fenced=False) == "success"
    assert metrics._classify_outcome(403, fenced=False) == "auth_error"
    assert metrics._classify_outcome(503, fenced=False) == "auth_error"
    assert metrics._classify_outcome(500, fenced=False) == "error"
