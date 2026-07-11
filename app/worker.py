import json
import logging

from celery import Celery

from app.core.config import settings
from app.core.redis import create_sync_redis, session_channel
from app.graph import compiled_graph
from app.graph.schemas import Panel
from app.graph.state import build_initial_state

logger = logging.getLogger(__name__)

celery_app = Celery(
    "tess_worker",
    broker=settings.redis_url,
    backend=settings.redis_url,
)


def _publish_error(redis_client, channel: str, message: str) -> None:
    """Publish an error envelope to the session channel."""
    error_payload = json.dumps({"type": "error", "message": message})
    redis_client.publish(channel, error_payload)


def _publish_panels(redis_client, channel: str, panels: list[Panel]) -> None:
    """Publish each Panel as JSON to the session channel."""
    for panel in panels:
        redis_client.publish(channel, panel.model_dump_json())


@celery_app.task(name="process_user_input")
def process_user_input(user_input: str, session_id: str) -> None:
    """Run the LangGraph chain and stream resulting Panels via Redis Pub/Sub."""
    channel = session_channel(session_id)
    redis_client = create_sync_redis()

    try:
        result = compiled_graph.invoke(build_initial_state(user_input))
        panels: list[Panel] = result.get("panels", [])

        if not panels:
            logger.warning("Graph completed with no panels for session %s", session_id)
            _publish_error(redis_client, channel, "Graph completed with no panels.")
            return

        _publish_panels(redis_client, channel, panels)
    except Exception as exc:
        logger.exception("Failed to process user input for session %s", session_id)
        _publish_error(redis_client, channel, str(exc))
    finally:
        redis_client.close()
