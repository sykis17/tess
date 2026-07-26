"""Authority selection + absent-blob restore behavior (post-cutover).

``ops_fence_authority`` picks which backend is authoritative for durable CP writes;
HA-off ignores the flag entirely (single-writer Redis).

After the etcd cutover there is **no Redis fallback** in ``restore_store``: an absent
etcd durable blob returns empty and logs loudly (fresh cluster -> the primary persists
on first election; otherwise explicit recovery). The stale Redis blob is never
resurrected — that fossil is exactly what the dual-write-removal step retired.
"""

from __future__ import annotations

import json

import pytest

from app.core.config import settings
from app.ops.models import CloudProvider, ProviderType
from app.ops.store import (
    REDIS_CONTROL_PLANE_KEY,
    EtcdFenceStore,
    OpsStore,
    RedisFenceStore,
    get_fence_store,
    get_store,
    reset_fence_store,
    reset_store,
    restore_store,
    set_fence_store,
)
from tests.fence_fakes import _FakeRedis


@pytest.fixture(autouse=True)
def _authority_cleanup(monkeypatch: pytest.MonkeyPatch):
    # The global conftest defaults HA off + authority redis; this file flips them per test.
    reset_store()
    reset_fence_store()
    yield
    reset_store()
    reset_fence_store()


def _activate_ha(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ops_ha_enabled", True)
    monkeypatch.setattr(
        settings, "ops_etcd_endpoints", "http://etcd1:2379,http://etcd2:2379"
    )


def test_authority_flag_selects_authoritative_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _activate_ha(monkeypatch)

    monkeypatch.setattr(settings, "ops_fence_authority", "etcd")
    reset_fence_store()
    assert isinstance(get_fence_store(), EtcdFenceStore)

    monkeypatch.setattr(settings, "ops_fence_authority", "redis")
    reset_fence_store()
    assert isinstance(get_fence_store(), RedisFenceStore)


def test_ha_off_ignores_authority_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ops_ha_enabled", False)
    # Even with the flag set to etcd, HA-off stays on the unconditional Redis writer.
    monkeypatch.setattr(settings, "ops_fence_authority", "etcd")
    reset_fence_store()
    assert isinstance(get_fence_store(), RedisFenceStore)


class _EtcdAbsentStore:
    """Authoritative-store stand-in whose durable blob is absent (fresh etcd).

    Records any write so the test can prove restore never wrote the authoritative backend.
    """

    def __init__(self) -> None:
        self.writes: list[str] = []
        self.promotes: list[int] = []
        self.cas: list[int] = []

    def read_term(self) -> int:
        return 0

    def read_blob(self) -> str | None:
        return None

    def write_blob(self, payload: str) -> None:
        self.writes.append(payload)

    def promote_term(self, term: int) -> bool:
        self.promotes.append(term)
        return True

    def cas_persist(self, term: int, payload: str) -> bool:
        self.cas.append(term)
        return True


def _redis_blob_with_one_provider(fence_term: int) -> str:
    tmp = OpsStore()
    tmp.upsert_provider(
        CloudProvider(
            id="prov_fossil",
            type=ProviderType.HETZNER,
            name="Fossil",
            base_url="http://fossil.example",
        )
    )
    return json.dumps(tmp.to_redis_payload(fence_term=fence_term))


def test_restore_no_redis_fallback_when_etcd_blob_absent(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Absent etcd blob -> empty restore + loud warning; the stale Redis blob is NOT adopted."""
    _activate_ha(monkeypatch)
    monkeypatch.setattr(settings, "ops_persist_enabled", True)
    monkeypatch.setattr(settings, "ops_fence_authority", "etcd")

    absent = _EtcdAbsentStore()
    set_fence_store(absent)  # authoritative etcd blob absent

    fake = _FakeRedis()
    fake.set(REDIS_CONTROL_PLANE_KEY, _redis_blob_with_one_provider(7))  # stale fossil
    monkeypatch.setattr("app.ops.store._redis_client", lambda: fake)

    reset_store()
    with caplog.at_level("WARNING"):
        ok = restore_store()

    assert ok is False  # no fallback: empty restore
    assert get_store().list_providers() == []  # the Redis fossil was NOT resurrected
    # Loud: the absent-blob path warned about explicit recovery / no fallback.
    assert any(
        "no Redis fallback" in r.getMessage()
        or "recover the durable blob" in r.getMessage()
        for r in caplog.records
    )
    # Never wrote the authoritative etcd backend during a read-only restore.
    assert absent.writes == []
    assert absent.cas == []
    assert absent.promotes == []


def test_restore_absent_blob_under_redis_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis authority, no blob => no restore (and no etcd-absent warning path)."""
    _activate_ha(monkeypatch)
    monkeypatch.setattr(settings, "ops_persist_enabled", True)
    monkeypatch.setattr(settings, "ops_fence_authority", "redis")

    fake = _FakeRedis()  # no control-plane blob seeded
    monkeypatch.setattr("app.ops.store._redis_client", lambda: fake)
    reset_fence_store()

    reset_store()
    assert restore_store() is False
    assert get_store().list_providers() == []
