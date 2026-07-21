"""Unit tests for provider_changed Redis fan-out."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.core.redis import OPS_PROVIDER_CHANGED_CHANNEL
from app.ops.failover import force_active_provider
from app.ops.models import (
    CloudProvider,
    ProviderChangedMessage,
    ProviderType,
    SessionAssignment,
)
from app.ops.notify import publish_provider_changed
from app.ops.store import OpsStore


def test_ops_provider_changed_channel_name() -> None:
    assert OPS_PROVIDER_CHANGED_CHANNEL == "ops:provider_changed"


def test_provider_changed_message_serializes_for_ws() -> None:
    msg = ProviderChangedMessage(
        from_provider_id="a",
        to_provider_id="b",
        sessions_dropped=2,
        ws_base_url="ws://standby.example",
    )
    payload = json.loads(msg.model_dump_json())
    assert payload["type"] == "provider_changed"
    assert payload["from_provider_id"] == "a"
    assert payload["to_provider_id"] == "b"
    assert payload["sessions_dropped"] == 2
    assert payload["ws_base_url"] == "ws://standby.example"
    assert "message" in payload and payload["message"]


def test_publish_provider_changed_uses_ops_channel() -> None:
    msg = ProviderChangedMessage(
        from_provider_id="a",
        to_provider_id="b",
        sessions_dropped=0,
    )
    mock_client = MagicMock()
    with patch("app.ops.notify.redis.from_url", return_value=mock_client):
        publish_provider_changed(msg)

    mock_client.publish.assert_called_once()
    channel, raw = mock_client.publish.call_args.args
    assert channel == OPS_PROVIDER_CHANGED_CHANNEL
    assert json.loads(raw)["type"] == "provider_changed"
    mock_client.close.assert_called_once()


def test_publish_provider_changed_swallows_redis_errors() -> None:
    msg = ProviderChangedMessage(to_provider_id="b")
    mock_client = MagicMock()
    mock_client.publish.side_effect = RuntimeError("redis down")
    with patch("app.ops.notify.redis.from_url", return_value=mock_client):
        publish_provider_changed(msg)  # must not raise
    mock_client.close.assert_called_once()


def test_force_active_publishes_provider_changed() -> None:
    store = OpsStore()
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
            ws_base_url="ws://b.example",
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

    with patch("app.ops.failover.publish_provider_changed") as publish:
        msg = force_active_provider("b", store=store)

    assert msg.to_provider_id == "b"
    assert msg.sessions_dropped == 1
    publish.assert_called_once()
    published = publish.call_args.args[0]
    assert isinstance(published, ProviderChangedMessage)
    assert published.from_provider_id == "a"
    assert published.to_provider_id == "b"
    assert published.sessions_dropped == 1
