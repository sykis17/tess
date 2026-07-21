"""Best-effort Redis fan-out for ops control-plane events."""

from __future__ import annotations

import logging

import redis

from app.core.config import settings
from app.core.redis import OPS_PROVIDER_CHANGED_CHANNEL
from app.ops.models import ProviderChangedMessage

logger = logging.getLogger(__name__)


def publish_provider_changed(msg: ProviderChangedMessage) -> None:
    """Publish a provider_changed envelope to all open WebSocket subscribers."""
    redis_client = redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
    )
    try:
        redis_client.publish(OPS_PROVIDER_CHANGED_CHANNEL, msg.model_dump_json())
    except Exception:
        logger.exception(
            "Failed to publish provider_changed (%s -> %s)",
            msg.from_provider_id,
            msg.to_provider_id,
        )
    finally:
        redis_client.close()
