"""P0.2: /ops/routing/notice serves last_failover_at; format identity across carriers.

The frontend classifies a disconnect as "provider changed" only when the
server-authored last_failover_at CHANGED between socket open and close,
compared as an opaque string (docs/P0_OPENER.md). Two carriers ship that
string — the public notice and the pubsub ProviderChangedMessage — and they
must be byte-identical for the same switch (cold-review N1: a datetime-typed
message field would serialize to "...Z" while the notice serves isoformat's
"...+00:00", silently re-opening the fabrication the design closes).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.ops.failover import force_active_provider
from app.ops.models import CloudProvider, ProviderType
from app.ops.store import get_store, reset_store


@pytest.fixture(autouse=True)
def _fresh_store():
    reset_store()
    yield
    reset_store()


def _seed_providers() -> None:
    store = get_store()
    store.upsert_provider(
        CloudProvider(
            id="a", type=ProviderType.HETZNER, name="A", base_url="http://a.example"
        )
    )
    store.upsert_provider(
        CloudProvider(
            id="b",
            type=ProviderType.AWS,
            name="B",
            base_url="http://b.example",
            ws_base_url="ws://b.example",
        )
    )


def test_notice_last_failover_at_null_before_any_switch() -> None:
    _seed_providers()
    body = TestClient(app).get("/ops/routing/notice").json()
    assert body["last_failover_at"] is None


def test_notice_last_failover_at_changes_across_switches() -> None:
    # The switch stamp is patched deterministic: on Windows CPython < 3.13,
    # time.time() ticks at ~15.6 ms, so two fast switches can land in one tick
    # and stamp identically (the opener's accepted row-13 corner, widened by
    # the platform clock). The semantics under test are "a switch changes the
    # notice value", not wall-clock granularity.
    _seed_providers()
    client = TestClient(app)
    stamps = iter(
        [
            datetime(2026, 7, 29, 10, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 7, 29, 10, 0, 1, tzinfo=timezone.utc),
        ]
    )

    with patch("app.ops.failover.utc_now", side_effect=lambda: next(stamps)):
        with patch("app.ops.failover.publish_provider_changed"):
            force_active_provider("b", store=get_store())
            first = client.get("/ops/routing/notice").json()["last_failover_at"]
            force_active_provider("a", store=get_store())
    second = client.get("/ops/routing/notice").json()["last_failover_at"]

    assert isinstance(first, str) and first
    assert isinstance(second, str) and second != first


def test_notice_and_message_carry_identical_last_failover_at() -> None:
    _seed_providers()
    with patch("app.ops.failover.publish_provider_changed"):
        msg = force_active_provider("b", store=get_store())

    notice = TestClient(app).get("/ops/routing/notice").json()
    assert isinstance(msg.last_failover_at, str) and msg.last_failover_at
    assert msg.last_failover_at == notice["last_failover_at"]
