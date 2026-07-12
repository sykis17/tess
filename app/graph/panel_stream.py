"""Publish intermediate Panels mid-node for long-running LLM stages."""

from app.core.redis import create_sync_redis, session_channel
from app.graph.schemas import Panel


def publish_panel(panel: Panel, session_id: str) -> None:
    """Publish a Panel to the session Redis channel (best-effort)."""
    if not session_id:
        return

    redis_client = create_sync_redis()
    try:
        channel = session_channel(session_id)
        redis_client.publish(channel, panel.model_dump_json())
    finally:
        redis_client.close()
