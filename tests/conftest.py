"""Shared pytest fixtures for TESS Engine tests."""

import pytest

from app.core.config import settings
from app.ops.store import reset_fence_store, reset_store


@pytest.fixture(autouse=True)
def _disable_ops_redis_persist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid hanging on unreachable Redis during unit tests."""
    monkeypatch.setattr(settings, "ops_persist_enabled", False)
    monkeypatch.setattr(settings, "ops_probe_enabled", False)
    monkeypatch.setattr(settings, "ops_ha_enabled", False)
    monkeypatch.setattr(settings, "ops_etcd_endpoints", "")
    reset_store()
    # Rebuild the authoritative fence store per (HA-off) settings so an authority=etcd
    # test can't leak a cached etcd store into the next test.
    reset_fence_store()
