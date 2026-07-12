import logging
from typing import Any

from app.graph.defense_utils import normalize_segments_for_review
from app.graph.schemas import AgentTrace, OUTPUT_PREVIEW_MAX_CHARS
from app.graph.state import GraphState
from app.graph.trace_utils import truncate_preview

logger = logging.getLogger(__name__)


async def defense_delegator_node(state: GraphState) -> dict[str, Any]:
    """Prepare answer segments for defense review."""
    segments = normalize_segments_for_review(state)

    logger.info("Defense Delegator prepared %d segments for review", len(segments))

    preview = truncate_preview(
        ", ".join(segment.title for segment in segments[:3]) or "No segments",
        OUTPUT_PREVIEW_MAX_CHARS,
    )
    trace = AgentTrace(
        agent_name="defense_delegator",
        inputs_seen=[
            f"usable_answers ({len(state.get('usable_answers') or [])} segments)",
            f"mayor_data ({len(state.get('mayor_data') or [])} entries)",
            f"combiners_bypassed ({state.get('combiners_bypassed', False)})",
        ],
        task_summary=state.get("current_task") or None,
        output_preview=preview,
    )

    return {
        "usable_answers": segments,
        "agent_traces": [trace],
    }
