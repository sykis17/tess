import logging
from typing import Any

from app.graph.combiner_utils import sort_usable_answers
from app.graph.schemas import AgentTrace, OUTPUT_PREVIEW_MAX_CHARS
from app.graph.state import GraphState
from app.graph.trace_utils import truncate_preview

logger = logging.getLogger(__name__)


async def collector_node(state: GraphState) -> dict[str, Any]:
    """Sort and sequence usable answers for presentation."""
    usable_answers = state.get("usable_answers") or []
    ordered = sort_usable_answers(usable_answers)

    logger.info("Collector ordered %d usable answer segments", len(ordered))

    titles = ", ".join(answer.title for answer in ordered[:3])
    if len(ordered) > 3:
        titles += f" (+{len(ordered) - 3} more)"

    trace = AgentTrace(
        agent_name="collector",
        inputs_seen=[f"usable_answers ({len(usable_answers)} segments)"],
        task_summary=state.get("current_task") or None,
        output_preview=truncate_preview(titles or "No segments to order", OUTPUT_PREVIEW_MAX_CHARS),
    )

    return {
        "usable_answers": ordered,
        "agent_traces": [trace],
    }
