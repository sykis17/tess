"""Shadow dual-write (Quorum Fence Store step 4).

The shadow etcd write must: record match/diverge/unavailable correctly, never raise,
and never change the authoritative (Redis) outcome. Real etcd shadowing is exercised
end-to-end by the split-brain harness run with OPS_FENCE_SHADOW=true.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.ops.consensus import InMemoryConsensus, set_consensus_backend
from app.ops.fencing import (
    clear_demote_callbacks,
    mark_primary,
    set_ha_disabled_role,
    write_fence,
)
from app.ops.store import (
    REDIS_CONTROL_PLANE_KEY,
    persist_store,
    reset_fence_store,
    reset_shadow_fence_store,
    reset_store,
    set_shadow_fence_store,
)
from tests.fence_fakes import _FakeRedis


class _FakeFenceStore:
    """In-memory FenceStore for shadow tests (no etcd needed)."""

    def __init__(self, *, term: int = 0, raise_on_cas: bool = False) -> None:
        self._term = term
        self._blob: str | None = None
        self._raise = raise_on_cas

    def read_term(self) -> int:
        return self._term

    def read_blob(self) -> str | None:
        return self._blob

    def write_blob(self, payload: str) -> None:
        self._blob = payload

    def promote_term(self, term: int) -> bool:
        if self._term <= term:
            self._term = term
            return True
        return False

    def cas_persist(self, term: int, payload: str) -> bool:
        if self._raise:
            raise RuntimeError("etcd shadow unreachable")
        if self._term == term:
            self._blob = payload
            return True
        return False


@pytest.fixture(autouse=True)
def _cleanup(monkeypatch: pytest.MonkeyPatch):
    clear_demote_callbacks()
    set_ha_disabled_role()
    set_consensus_backend(None)
    reset_store()
    reset_shadow_fence_store()
    yield
    set_ha_disabled_role()
    set_consensus_backend(None)
    reset_store()
    reset_shadow_fence_store()


def _enable_shadow(monkeypatch: pytest.MonkeyPatch, *, on: bool = True) -> None:
    monkeypatch.setattr(settings, "ops_ha_enabled", True)
    monkeypatch.setattr(settings, "ops_etcd_endpoints", "http://etcd:2379")
    monkeypatch.setattr(settings, "ops_persist_enabled", True)
    monkeypatch.setattr(settings, "ops_fence_shadow", on)
    # Authoritative = Redis (via _FakeRedis), shadow = the injected fake etcd store: this
    # covers the forward-shadow direction. Pin authority so the default (now "etcd") does
    # not swap the authoritative backend out from under the fake. Reverse-shadow (Redis
    # shadows etcd) is exercised by the split-brain harness soak.
    monkeypatch.setattr(settings, "ops_fence_authority", "redis")
    monkeypatch.setattr(settings, "ops_cp_instance_id", "cp-a")
    set_consensus_backend(InMemoryConsensus())
    reset_fence_store()


def _spy_shadow(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.ops.metrics.record_fence_shadow",
        lambda op, outcome: calls.append((op, outcome)),
    )
    return calls


def _persist_as_primary(term: int) -> None:
    mark_primary(term, lease_id=1)
    with write_fence(term):
        persist_store(fence_term=term)


def test_shadow_records_match_when_both_accept(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_shadow(monkeypatch)
    calls = _spy_shadow(monkeypatch)
    fake = _FakeRedis(fence_term=3)
    monkeypatch.setattr("app.ops.store._redis_client", lambda: fake)
    set_shadow_fence_store(_FakeFenceStore(term=3))  # agrees with the authoritative term

    _persist_as_primary(3)

    assert ("persist", "match") in calls
    assert REDIS_CONTROL_PLANE_KEY in fake.kv  # authoritative write still happened


def test_shadow_records_diverge_when_outcomes_differ(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_shadow(monkeypatch)
    calls = _spy_shadow(monkeypatch)
    fake = _FakeRedis(fence_term=3)  # authoritative accepts term 3
    monkeypatch.setattr("app.ops.store._redis_client", lambda: fake)
    set_shadow_fence_store(_FakeFenceStore(term=9))  # etcd term disagrees -> shadow rejects

    _persist_as_primary(3)

    assert ("persist", "diverge") in calls
    assert REDIS_CONTROL_PLANE_KEY in fake.kv  # divergence never blocks the authoritative write


def test_shadow_records_unavailable_when_shadow_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_shadow(monkeypatch)
    calls = _spy_shadow(monkeypatch)
    fake = _FakeRedis(fence_term=3)
    monkeypatch.setattr("app.ops.store._redis_client", lambda: fake)
    set_shadow_fence_store(_FakeFenceStore(term=3, raise_on_cas=True))

    _persist_as_primary(3)  # must not raise

    assert ("persist", "unavailable") in calls
    assert REDIS_CONTROL_PLANE_KEY in fake.kv  # authoritative path unaffected by shadow failure


def test_shadow_off_by_default_no_shadow_call(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_shadow(monkeypatch, on=False)
    calls = _spy_shadow(monkeypatch)
    fake = _FakeRedis(fence_term=3)
    monkeypatch.setattr("app.ops.store._redis_client", lambda: fake)
    # Inject a store that would raise if touched — proving it is never called when off.
    set_shadow_fence_store(_FakeFenceStore(term=3, raise_on_cas=True))

    _persist_as_primary(3)

    assert calls == []
    assert REDIS_CONTROL_PLANE_KEY in fake.kv
