"""Authority selection + first-boot migration fallback (Quorum Fence Store step 5a).

``ops_fence_authority`` picks which backend is authoritative for durable CP writes,
and the shadow is always the *other* backend so the dual-write direction reverses
structurally at cutover. HA-off ignores the flag entirely (single-writer Redis).

``restore_store`` gets a read-only Redis-blob fallback for the migration window: a
deploy that flips authority to etcd before the etcd blob was ever written must not
silently lose the pre-cutover control plane. The fallback is READ-ONLY (restore runs
at boot before election; writing etcd there would be an unfenced durable write) and
loud. It is removed in the dual-write-removal step.
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
    get_shadow_fence_store,
    get_store,
    reset_fence_store,
    reset_shadow_fence_store,
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
    reset_shadow_fence_store()
    yield
    reset_store()
    reset_fence_store()
    reset_shadow_fence_store()


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


def test_shadow_is_the_non_authoritative_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shadow reverses structurally at cutover (no second flag)."""
    _activate_ha(monkeypatch)

    # etcd authoritative -> Redis shadows it.
    monkeypatch.setattr(settings, "ops_fence_authority", "etcd")
    reset_fence_store()
    reset_shadow_fence_store()
    assert isinstance(get_shadow_fence_store(), RedisFenceStore)

    # redis authoritative -> etcd shadows it.
    monkeypatch.setattr(settings, "ops_fence_authority", "redis")
    reset_fence_store()
    reset_shadow_fence_store()
    assert isinstance(get_shadow_fence_store(), EtcdFenceStore)


class _EtcdAbsentStore:
    """Authoritative-store stand-in whose durable blob is absent (fresh etcd).

    Records any write so the test can prove the migration fallback never wrote to
    the authoritative backend during restore.
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
            id="prov_migrated",
            type=ProviderType.HETZNER,
            name="Migrated",
            base_url="http://migrated.example",
        )
    )
    return json.dumps(tmp.to_redis_payload(fence_term=fence_term))


def test_restore_adopts_redis_blob_readonly_when_etcd_absent(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _activate_ha(monkeypatch)
    monkeypatch.setattr(settings, "ops_persist_enabled", True)
    monkeypatch.setattr(settings, "ops_fence_authority", "etcd")

    absent = _EtcdAbsentStore()
    set_fence_store(absent)  # authoritative etcd blob is absent

    fake = _FakeRedis()
    fake.set(REDIS_CONTROL_PLANE_KEY, _redis_blob_with_one_provider(7))
    monkeypatch.setattr("app.ops.store._redis_client", lambda: fake)

    reset_store()  # in-memory empty before restore
    with caplog.at_level("WARNING"):
        ok = restore_store()

    assert ok is True
    # Pre-cutover state was adopted from Redis rather than lost.
    assert get_store().get_provider("prov_migrated") is not None
    # Loud: the migration fallback logged a warning.
    assert any(
        "READ-ONLY" in r.getMessage() or "migration" in r.getMessage().lower()
        for r in caplog.records
    )
    # Read-only: restore must NOT have written the authoritative (etcd) backend.
    assert absent.writes == []
    assert absent.cas == []
    assert absent.promotes == []


def test_restore_no_fallback_when_authority_is_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Under Redis authority the fallback branch is inert — absent blob => no restore."""
    _activate_ha(monkeypatch)
    monkeypatch.setattr(settings, "ops_persist_enabled", True)
    monkeypatch.setattr(settings, "ops_fence_authority", "redis")

    fake = _FakeRedis()  # no control-plane blob seeded
    monkeypatch.setattr("app.ops.store._redis_client", lambda: fake)
    reset_fence_store()

    reset_store()
    assert restore_store() is False
    assert get_store().list_providers() == []
