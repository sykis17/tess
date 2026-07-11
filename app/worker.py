import asyncio
import json
import logging

from celery import Celery
from celery.exceptions import SoftTimeLimitExceeded

from app.core.config import settings
from app.core.conversation import append_conversation_turn, load_conversation_history
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


def _extract_assistant_content(result: dict) -> str:
    """Extract the assistant response from graph state."""
    collected_data: list[str] = result.get("collected_data", [])
    if not collected_data:
        raise ValueError("Graph completed with no collected data.")
    return collected_data[-1]


@celery_app.task(name="process_user_input", soft_time_limit=120, time_limit=130)
def process_user_input(user_input: str, session_id: str) -> None:
    """Run the LangGraph chain and stream resulting Panels via Redis Pub/Sub."""
    channel = session_channel(session_id)
    redis_client = create_sync_redis()

    try:
        history = load_conversation_history(session_id)
        initial_state = build_initial_state(user_input, history)
        result = asyncio.run(compiled_graph.ainvoke(initial_state))
        panels: list[Panel] = result.get("panels", [])

        if not panels:
            logger.warning("Graph completed with no panels for session %s", session_id)
            _publish_error(redis_client, channel, "Graph completed with no panels.")
            return

        assistant_content = _extract_assistant_content(result)
        append_conversation_turn(session_id, user_input, assistant_content)
        _publish_panels(redis_client, channel, panels)
    except SoftTimeLimitExceeded:
        logger.error("Task timed out for session %s", session_id)
        _publish_error(
            redis_client,
            channel,
            "Request timed out. The server may be low on memory — try again in a moment.",
        )
    except Exception as exc:
        logger.exception("Failed to process user input for session %s", session_id)
        _publish_error(redis_client, channel, str(exc))
    finally:
        redis_client.close()
