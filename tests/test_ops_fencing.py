"""Fencing / etcd HA unit tests for the ops control plane."""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.ops.consensus import InMemoryConsensus, LiveElection, set_consensus_backend
from app.ops.failover import force_active_provider
from app.ops.fencing import (
    FenceCasError,
    FenceError,
    NotPrimaryError,
    check_fence_live,
    clear_demote_callbacks,
    get_role_state,
    mark_primary,
    mark_standby,
    require_primary_cached,
    set_ha_disabled_role,
    write_fence,
)
from app.ops.models import CloudProvider, ProviderType, SessionAssignment
from app.ops.store import (
    REDIS_CONTROL_PLANE_KEY,
    REDIS_FENCE_TERM_KEY,
    get_store,
    persist_store,
    promote_fence,
    reset_fence_store,
    reset_store,
)
from tests.fence_fakes import _FakeRedis


@pytest.fixture(autouse=True)
def _fencing_cleanup(monkeypatch: pytest.MonkeyPatch):
    clear_demote_callbacks()
    set_ha_disabled_role()
    set_consensus_backend(None)
    reset_store()
    monkeypatch.setattr(settings, "ops_cp_instance_id", "cp-a")
    yield
    clear_demote_callbacks()
    set_consensus_backend(None)
    set_ha_disabled_role()
    reset_store()


def _enable_ha(monkeypatch: pytest.MonkeyPatch, backend: InMemoryConsensus) -> None:
    monkeypatch.setattr(settings, "ops_ha_enabled", True)
    monkeypatch.setattr(settings, "ops_etcd_endpoints", "http://etcd:2379")
    monkeypatch.setattr(settings, "ops_persist_enabled", True)
    # These tests exercise the Redis CAS backend explicitly (via _FakeRedis); pin the
    # authority so they don't depend on the default (now "etcd") or on build-order caching.
    monkeypatch.setattr(settings, "ops_fence_authority", "redis")
    set_consensus_backend(backend)
    reset_fence_store()


def _seed_two_providers() -> None:
    store = get_store()
    store.upsert_provider(
        CloudProvider(
            id="a",
            type=ProviderType.HETZNER,
            name="A",
            base_url="http://a.example",
        )
    )
    store.upsert_provider(
        CloudProvider(
            id="b",
            type=ProviderType.AWS,
            name="B",
            base_url="http://b.example",
        )
    )
    store.routing.active_provider_id = "a"
    store.set_assignment(
        SessionAssignment(
            session_id="s1",
            provider_id="a",
            policy=store.get_policy().policy,
        )
    )


def test_promote_and_persist_cas_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = InMemoryConsensus()
    _enable_ha(monkeypatch, backend)
    fake = _FakeRedis(fence_term=0)
    monkeypatch.setattr("app.ops.store._redis_client", lambda: fake)

    promote_fence(3)
    assert fake.get(REDIS_FENCE_TERM_KEY) == "3"

    mark_primary(3, lease_id=1)
    with write_fence(3):
        persist_store(fence_term=3)
    assert REDIS_CONTROL_PLANE_KEY in fake.kv
    assert '"fence_term": 3' in fake.kv[REDIS_CONTROL_PLANE_KEY]


def test_stale_persist_cas_rejected_hard(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = InMemoryConsensus()
    _enable_ha(monkeypatch, backend)
    fake = _FakeRedis(fence_term=9)  # newer primary already installed
    monkeypatch.setattr("app.ops.store._redis_client", lambda: fake)
    mark_primary(5, lease_id=1)

    with pytest.raises(FenceCasError):
        persist_store(fence_term=5)
    assert get_role_state().role == "demoted"
    # Blob must not have been written by stale term
    assert REDIS_CONTROL_PLANE_KEY not in fake.kv


def test_toctou_etcd_yes_redis_cas_no_blocks_switch_and_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Highest-priority fence test: etcd prefilter OK, Redis CAS rejects.

    Caller must hard-fail identically to an etcd rejection: no durable side
    effects, no provider_changed publish, in-memory switch rolled back via restore.
    """
    backend = InMemoryConsensus()
    backend.force_leader("cp-a", term=5)
    _enable_ha(monkeypatch, backend)
    mark_primary(5, lease_id=42)

    # Redis already at term 6 (another primary won the TOCTOU window).
    fake = _FakeRedis(fence_term=6)
    # Pre-seed a clean blob so restore after CAS fail does not leave dirty memory.
    import json

    from app.ops.store import get_store as _gs

    _seed_two_providers()
    clean = json.dumps(_gs().to_redis_payload(fence_term=6))
    fake.set(REDIS_CONTROL_PLANE_KEY, clean)
    # Dirty local intent: still active=a; force_active will try to flip to b.
    assert get_store().get_routing().active_provider_id == "a"

    monkeypatch.setattr("app.ops.store._redis_client", lambda: fake)

    published: list = []

    def _capture(msg) -> None:
        published.append(msg)

    with patch("app.ops.failover.publish_provider_changed", side_effect=_capture):
        with pytest.raises(FenceError):
            force_active_provider("b")

    assert published == [], "CAS reject must not publish provider_changed"
    # Same severity class as etcd reject: demoted, not a soft warning.
    assert get_role_state().role == "demoted"
    # Restore rolled back any in-memory flip (blob still has active=a).
    assert get_store().get_routing().active_provider_id == "a"


def test_etcd_reject_same_severity_as_cas(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = InMemoryConsensus()
    backend.force_leader("cp-other", term=7)
    _enable_ha(monkeypatch, backend)
    mark_standby(primary_instance_id="cp-other", fence_term=7)

    with pytest.raises(NotPrimaryError):
        require_primary_cached()
    with pytest.raises(NotPrimaryError):
        check_fence_live()


def test_celery_uses_only_fresh_live_election(monkeypatch: pytest.MonkeyPatch) -> None:
    """Poisoned web role cache must not authorize Celery; only check_fence_live."""
    backend = InMemoryConsensus()
    backend.force_leader("cp-other", term=3)
    _enable_ha(monkeypatch, backend)
    # Poison cache: pretend we are primary with a high term.
    mark_primary(99, lease_id=1)
    assert require_primary_cached() == 99

    with pytest.raises(NotPrimaryError):
        check_fence_live()

    # Simulate Celery task path: fresh live check only.
    from app.worker import ops_probe_providers

    with pytest.raises(NotPrimaryError):
        ops_probe_providers()


def test_celery_task_bodies_do_not_read_cached_role() -> None:
    """Static guard: ops Celery tasks must not call require_primary_cached / get_role_state."""
    import app.worker as worker_mod

    for name in ("ops_probe_providers", "ops_standby_wake", "ops_standby_sleep"):
        fn = getattr(worker_mod, name)
        # Unwrap Celery task to underlying run if needed
        target = fn
        if hasattr(fn, "run"):
            # Celery Task.__call__ path — inspect the Python function source via module
            src = inspect.getsource(worker_mod)
        else:
            src = inspect.getsource(fn)
        # Narrow to the function block approximately
        start = src.find(f"def {name}")
        assert start >= 0, name
        chunk = src[start : start + 800]
        assert "require_primary_cached" not in chunk, name
        assert "get_role_state" not in chunk, name
        assert "check_fence_live" in chunk, name
        assert "write_fence(live.fence_term)" in chunk or "write_fence(live.fence_term)" in src


def test_worker_source_grep_no_stale_role_fields() -> None:
    """Broader grep: task helpers must not reference fencing module role cache APIs."""
    text = Path("app/worker.py").read_text(encoding="utf-8")
    # Only the three ops tasks should mention fencing; ensure no role-cache imports.
    assert "require_primary_cached" not in text
    assert "get_role_state" not in text
    assert "mark_primary" not in text
    assert text.count("check_fence_live") == 6  # import + call in each of 3 ops tasks


def test_check_fence_live_ha_disabled_is_synthetic() -> None:
    set_ha_disabled_role()
    live = check_fence_live()
    assert isinstance(live, LiveElection)
    assert live.leader == settings.ops_cp_instance_id
    assert live.fence_term == 0
