"""Shared pytest fixtures for TESS Engine tests."""

import pytest

from app.core.config import settings
from app.ops.store import reset_store


@pytest.fixture(autouse=True)
def _disable_ops_redis_persist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid hanging on unreachable Redis during unit tests."""
    monkeypatch.setattr(settings, "ops_persist_enabled", False)
    monkeypatch.setattr(settings, "ops_probe_enabled", False)
    reset_store()
