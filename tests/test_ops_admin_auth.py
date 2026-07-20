"""Admin token gating for mutating /ops endpoints (incl. force switch)."""

import pytest
from fastapi import HTTPException

from app.api.ops import _check_admin
from app.core.config import settings


def test_admin_fail_closed_when_token_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ops_admin_token", None)
    with pytest.raises(HTTPException) as exc:
        _check_admin(None)
    assert exc.value.status_code == 503
    assert "OPS_ADMIN_TOKEN" in str(exc.value.detail)


def test_admin_requires_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ops_admin_token", "secret-token")
    with pytest.raises(HTTPException) as exc:
        _check_admin(None)
    assert exc.value.status_code == 401

    with pytest.raises(HTTPException) as exc2:
        _check_admin("Token secret-token")
    assert exc2.value.status_code == 401


def test_admin_rejects_wrong_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ops_admin_token", "secret-token")
    with pytest.raises(HTTPException) as exc:
        _check_admin("Bearer wrong")
    assert exc.value.status_code == 403


def test_admin_accepts_valid_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ops_admin_token", "secret-token")
    _check_admin("Bearer secret-token")


def test_force_active_route_uses_admin_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: force switch must not be reachable without a configured token."""
    import asyncio

    from app.api import ops as ops_api

    monkeypatch.setattr(settings, "ops_admin_token", None)

    async def call() -> None:
        await ops_api.set_active("prov_hetzner_local", authorization=None)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(call())
    assert exc.value.status_code == 503
