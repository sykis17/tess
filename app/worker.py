import asyncio
import json
import logging
import time
import uuid
from typing import Any

import httpx
from celery import Celery
from celery.exceptions import SoftTimeLimitExceeded

from app.core.config import settings
from app.core.conversation import append_conversation_turn, load_conversation_history
from app.core.redis import create_sync_redis, session_channel
from app.core.session_control import (
    SessionInterrupted,
    clear_active_task_if_matches,
    clear_interrupt,
    is_session_interrupted,
)
from app.core.ws_payload import parse_incoming_payload
from app.graph import compiled_graph
from app.graph.combiner_utils import format_usable_answers_markdown
from app.graph.schemas import Panel
from app.graph.state import GraphState, build_initial_state

logger = logging.getLogger(__name__)

PIPELINE_SOFT_TIME_LIMIT_SECONDS = settings.pipeline_soft_time_limit_seconds
PIPELINE_HARD_TIME_LIMIT_SECONDS = settings.pipeline_hard_time_limit_seconds

celery_app = Celery(
    "tess_worker",
    broker=settings.redis_url,
    backend=settings.redis_url,
)


@celery_app.task(name="ops_probe_providers")
def ops_probe_providers() -> dict[str, object]:
    """Celery entry for scheduled multi-cloud health probes + failover."""
    from app.ops.failover import evaluate_failover
    from app.ops.prober import probe_all_providers

    snapshots = asyncio.run(probe_all_providers())
    failover_msg = evaluate_failover(snapshots)
    return {
        "probed": len(snapshots),
        "failover": failover_msg.model_dump(mode="json") if failover_msg else None,
    }


_REDUCER_KEYS = frozenset({
    "collected_data",
    "mayor_data",
    "panels",
    "agent_traces",
    "search_results",
    "fan_in_branches_done",
})


def _format_worker_error(exc: Exception) -> str:
    """Return a user-visible error message for worker failures."""
    if isinstance(exc, SoftTimeLimitExceeded):
        minutes = PIPELINE_SOFT_TIME_LIMIT_SECONDS // 60
        return (
            f"Pipeline timed out after {minutes} minutes. Multi-agent requests on a small "
            "server can take several minutes — combiner stages are the slowest. "
            "Please try again, use chain L1+ for faster output, or use a simpler prompt."
        )

    if isinstance(
        exc,
        (
            httpx.ReadTimeout,
            httpx.ConnectTimeout,
            httpx.TimeoutException,
            TimeoutError,
        ),
    ):
        return (
            "The AI model took too long to respond. On multi-agent requests this can take "
            "several minutes on a small server — please try again or use a simpler prompt."
        )

    message = str(exc).strip()
    if message:
        return message

    return "An unexpected error occurred while processing your request. Please try again."


def _publish_error(redis_client, channel: str, message: str) -> None:
    """Publish an error envelope to the session channel."""
    error_payload = json.dumps({"type": "error", "message": message})
    redis_client.publish(channel, error_payload)


def _publish_cancelled(redis_client, channel: str, message: str) -> None:
    """Publish a cancellation envelope to the session channel."""
    cancelled_payload = json.dumps({"type": "cancelled", "message": message})
    redis_client.publish(channel, cancelled_payload)


def _publish_panels(redis_client, channel: str, panels: list[Panel]) -> None:
    """Publish each Panel as JSON to the session channel."""
    for panel in panels:
        redis_client.publish(channel, panel.model_dump_json())


def _merge_node_output(merged: dict[str, Any], node_output: dict[str, Any] | None) -> None:
    """Merge a node update into the running graph state."""
    if not node_output:
        return
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

    usable_answers = result.get("usable_answers") or []
    if usable_answers:
        active_agents = result.get("active_agents") or []
        return format_usable_answers_markdown(usable_answers, active_agents)

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
    session_id: str,
) -> dict[str, Any]:
    """Run the graph and publish Panels incrementally as nodes complete."""
    merged: dict[str, Any] = dict(initial_state)
    pipeline_start = time.monotonic()
    node_start = pipeline_start

    async for update in compiled_graph.astream(initial_state, stream_mode="updates"):
        if is_session_interrupted(session_id):
            logger.info("Session %s interrupted between graph nodes", session_id)
            _publish_cancelled(
                redis_client,
                channel,
                "Previous request cancelled — processing your new message.",
            )
            return merged

        for node_name, node_output in update.items():
            if node_output is None:
                continue

            node_elapsed = time.monotonic() - node_start
            cumulative_elapsed = time.monotonic() - pipeline_start
            logger.info(
                "Node %s finished in %.1fs (cumulative %.1fs)",
                node_name,
                node_elapsed,
                cumulative_elapsed,
            )
            if node_name == "presenter":
                pre_presenter_elapsed = cumulative_elapsed - node_elapsed
                if pre_presenter_elapsed > 720:
                    logger.warning(
                        "Pipeline exceeded 12 min before presenter (%.1fs pre-presenter)",
                        pre_presenter_elapsed,
                    )
            node_start = time.monotonic()

            _merge_node_output(merged, node_output)

            panels = node_output.get("panels", [])
            if panels:
                _publish_panels(redis_client, channel, panels)

    return merged


@celery_app.task(
    name="process_user_input",
    soft_time_limit=PIPELINE_SOFT_TIME_LIMIT_SECONDS,
    time_limit=PIPELINE_HARD_TIME_LIMIT_SECONDS,
)
def process_user_input(payload: str, session_id: str) -> None:
    """Run the LangGraph chain and stream resulting Panels via Redis Pub/Sub."""
    channel = session_channel(session_id)
    redis_client = create_sync_redis()
    task_id = process_user_input.request.id

    try:
        clear_interrupt(session_id)

        user_text, product_mode, chain_profile = parse_incoming_payload(payload)
        history = load_conversation_history(session_id)
        panel_id = str(uuid.uuid4())
        initial_state = build_initial_state(
            user_text,
            history,
            panel_id=panel_id,
            session_id=session_id,
            product_mode=product_mode,
            chain_profile=chain_profile,
        )
        result = asyncio.run(
            _run_graph_with_streaming(initial_state, redis_client, channel, session_id)
        )

        if is_session_interrupted(session_id):
            logger.info("Session %s run ended due to interrupt", session_id)
            return

        panels: list[Panel] = result.get("panels", [])

        if not panels:
            logger.warning("Graph completed with no panels for session %s", session_id)
            _publish_error(redis_client, channel, "Graph completed with no panels.")
            return

        assistant_content = _extract_assistant_content(result)
        append_conversation_turn(session_id, user_text, assistant_content)
    except SessionInterrupted:
        logger.info("Session %s interrupted during streaming", session_id)
        _publish_cancelled(
            redis_client,
            channel,
            "Previous request cancelled — processing your new message.",
        )
    except SoftTimeLimitExceeded as exc:
        logger.error("Task timed out for session %s", session_id)
        _publish_error(redis_client, channel, _format_worker_error(exc))
    except Exception as exc:
        if is_session_interrupted(session_id):
            logger.info("Session %s interrupted (exception during teardown)", session_id)
            _publish_cancelled(
                redis_client,
                channel,
                "Previous request cancelled — processing your new message.",
            )
            return
        logger.exception("Failed to process user input for session %s", session_id)
        _publish_error(redis_client, channel, _format_worker_error(exc))
    finally:
        clear_active_task_if_matches(session_id, task_id)
        redis_client.close()
