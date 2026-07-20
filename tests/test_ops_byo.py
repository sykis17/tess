"""Customer BYO registration tests."""

import asyncio
from unittest.mock import patch

from app.ops.byo import register_customer_server
from app.ops.models import ByoRegisterRequest, HealthSnapshot
from app.ops.store import OpsStore
import pytest


def test_byo_requires_org_id() -> None:
    store = OpsStore()
    req = ByoRegisterRequest(
        name="Mine",
        base_url="http://mine.example",
        org_id="",
    )
    with pytest.raises(ValueError, match="org_id"):
        asyncio.run(register_customer_server(req, store=store, require_healthy=False))


def test_byo_health_gate_rejects() -> None:
    store = OpsStore()
    req = ByoRegisterRequest(
        name="Mine",
        base_url="http://mine.example",
        org_id="org-1",
    )

    async def bad_probe(provider, *, timeout_seconds=5.0, store=None):
        return HealthSnapshot(
            provider_id=provider.id,
            http_ok=False,
            score=0,
            healthy=False,
            last_error="down",
        )

    with patch("app.ops.byo.probe_provider", side_effect=bad_probe):
        with pytest.raises(ValueError, match="health gate"):
            asyncio.run(register_customer_server(req, store=store))


def test_byo_registers_when_healthy() -> None:
    store = OpsStore()
    req = ByoRegisterRequest(
        name="Mine",
        base_url="http://mine.example",
        org_id="org-1",
    )

    async def ok_probe(provider, *, timeout_seconds=5.0, store=None):
        return HealthSnapshot(
            provider_id=provider.id,
            http_ok=True,
            score=90,
            healthy=True,
            redis_ok=True,
        )

    with patch("app.ops.byo.probe_provider", side_effect=ok_probe):
        provider = asyncio.run(register_customer_server(req, store=store))

    assert provider.org_id == "org-1"
    assert provider.type.value == "customer"
    assert store.get_provider(provider.id) is not None
    assert any(e.event_type == "byo_registered" for e in store.list_events())
