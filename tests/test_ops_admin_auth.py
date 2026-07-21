"""Admin token gating for /ops endpoints (multi-operator + legacy)."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.ops import admin_auth
from app.ops.admin_auth import _check_admin, load_admin_tokens, resolve_operator
from app.ops.store import get_store


@pytest.fixture(autouse=True)
def _clear_admin_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ops_admin_token", None)
    monkeypatch.setattr(settings, "ops_admin_tokens", None)


def test_admin_fail_closed_when_token_unset() -> None:
    with pytest.raises(HTTPException) as exc:
        _check_admin(None)
    assert exc.value.status_code == 503
    assert "OPS_ADMIN" in str(exc.value.detail)


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
    assert resolve_operator("Bearer secret-token") == admin_auth.LEGACY_OPERATOR_ID


def test_multi_token_resolves_named_operator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings,
        "ops_admin_tokens",
        json.dumps({"jesse": "jesse-secret", "alice": "alice-secret"}),
    )
    assert resolve_operator("Bearer jesse-secret") == "jesse"
    assert resolve_operator("Bearer alice-secret") == "alice"
    with pytest.raises(HTTPException) as exc:
        resolve_operator("Bearer nope")
    assert exc.value.status_code == 403


def test_legacy_token_still_works_alongside_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ops_admin_token", "legacy-secret")
    monkeypatch.setattr(
        settings,
        "ops_admin_tokens",
        json.dumps({"jesse": "jesse-secret"}),
    )
    tokens = load_admin_tokens()
    assert tokens["jesse"] == "jesse-secret"
    assert tokens["legacy"] == "legacy-secret"
    assert resolve_operator("Bearer legacy-secret") == "legacy"
    assert resolve_operator("Bearer jesse-secret") == "jesse"


def test_invalid_ops_admin_tokens_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ops_admin_tokens", "not-json")
    with pytest.raises(HTTPException) as exc:
        load_admin_tokens()
    assert exc.value.status_code == 503


def test_force_active_route_uses_admin_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: force switch must not be reachable without a configured token."""
    client = TestClient(app)
    monkeypatch.setattr(settings, "ops_admin_token", None)
    monkeypatch.setattr(settings, "ops_admin_tokens", None)
    res = client.post("/ops/routing/active/prov_hetzner_local")
    assert res.status_code == 503


def test_gated_get_requires_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ops_admin_token", "secret-token")
    client = TestClient(app)
    res = client.get("/ops/providers")
    assert res.status_code == 401
    res_ok = client.get(
        "/ops/providers",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert res_ok.status_code == 200


def test_routing_notice_is_public(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ops_admin_token", "secret-token")
    store = get_store()
    routing = store.get_routing()
    routing.sessions_dropped_last = 3
    store.set_routing(routing)

    client = TestClient(app)
    res = client.get("/ops/routing/notice")
    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) == {"ws_base_url", "sessions_dropped_last"}
    assert body["sessions_dropped_last"] == 3
    assert "policy" not in body
    assert "routing" not in body
    assert "providers" not in body


def test_full_routing_requires_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ops_admin_token", "secret-token")
    client = TestClient(app)
    assert client.get("/ops/routing").status_code == 401
    ok = client.get(
        "/ops/routing",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert ok.status_code == 200
    assert "policy" in ok.json()


def test_assign_requires_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ops_admin_token", "secret-token")
    client = TestClient(app)
    assert client.post("/ops/sessions/sess_test/assign").status_code == 401
