import asyncio
import json
import logging
import uuid
from typing import Any

from celery import Celery
from celery.exceptions import SoftTimeLimitExceeded

from app.core.config import settings
from app.core.conversation import append_conversation_turn, load_conversation_history
from app.core.redis import create_sync_redis, session_channel
from app.graph import compiled_graph
from app.graph.schemas import Panel
from app.graph.state import GraphState, build_initial_state

logger = logging.getLogger(__name__)

celery_app = Celery(
    "tess_worker",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

_REDUCER_KEYS = frozenset({"collected_data", "mayor_data", "panels", "agent_traces", "search_results"})


def _publish_error(redis_client, channel: str, message: str) -> None:
    """Publish an error envelope to the session channel."""
    error_payload = json.dumps({"type": "error", "message": message})
    redis_client.publish(channel, error_payload)


def _publish_panels(redis_client, channel: str, panels: list[Panel]) -> None:
    """Publish each Panel as JSON to the session channel."""
    for panel in panels:
        redis_client.publish(channel, panel.model_dump_json())


def _merge_node_output(merged: dict[str, Any], node_output: dict[str, Any]) -> None:
    """Merge a node update into the running graph state."""
    for key, value in node_output.items():
        if key in _REDUCER_KEYS:
            merged[key] = [*merged.get(key, []), *value]
        else:
            merged[key] = value


def _extract_assistant_content(result: dict[str, Any]) -> str:
    """Extract the assistant response from graph state."""
    panels: list[Panel] = result.get("panels", [])
    for panel in reversed(panels):
        if panel.status == "completed":
            return panel.content

    mayor_data = result.get("mayor_data", [])
    if mayor_data:
        return "\n\n".join(entry.content for entry in mayor_data)

    collected_data: list[str] = result.get("collected_data", [])
    if not collected_data:
        raise ValueError("Graph completed with no collected data.")
    return collected_data[-1]


async def _run_graph_with_streaming(
    initial_state: GraphState,
    redis_client,
    channel: str,
) -> dict[str, Any]:
    """Run the graph and publish Panels incrementally as nodes complete."""
    merged: dict[str, Any] = dict(initial_state)

    async for update in compiled_graph.astream(initial_state, stream_mode="updates"):
        for _node_name, node_output in update.items():
            _merge_node_output(merged, node_output)

            panels = node_output.get("panels", [])
            if panels:
                _publish_panels(redis_client, channel, panels)

    return merged


@celery_app.task(name="process_user_input", soft_time_limit=360, time_limit=370)
def process_user_input(user_input: str, session_id: str) -> None:
    """Run the LangGraph chain and stream resulting Panels via Redis Pub/Sub."""
    channel = session_channel(session_id)
    redis_client = create_sync_redis()

    try:
        history = load_conversation_history(session_id)
        panel_id = str(uuid.uuid4())
        initial_state = build_initial_state(user_input, history, panel_id=panel_id, session_id=session_id)
        result = asyncio.run(
            _run_graph_with_streaming(initial_state, redis_client, channel)
        )
        panels: list[Panel] = result.get("panels", [])

        if not panels:
            logger.warning("Graph completed with no panels for session %s", session_id)
            _publish_error(redis_client, channel, "Graph completed with no panels.")
            return

        assistant_content = _extract_assistant_content(result)
        append_conversation_turn(session_id, user_input, assistant_content)
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
