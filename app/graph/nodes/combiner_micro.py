import logging
import time
from typing import Any

from app.agents.registry import get_agent, DEFAULT_AGENT_NAME
from app.agents.subjects.registry import collect_pov_sources
from app.graph.combiner_utils import (
    build_agents_involved,
    parse_usable_answers_json,
    serialize_micro_data_for_llm,
)
from app.graph.panel_stream import publish_panel
from app.graph.prompts import COMBINER_MICRO_SYSTEM_PROMPT
from app.graph.schemas import AgentTrace, OUTPUT_PREVIEW_MAX_CHARS, Panel
from app.graph.state import GraphState
from app.graph.trace_utils import truncate_preview
from app.llm.factory import create_llm
from app.llm.types import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)


def _resolve_folder_path(state: GraphState) -> str:
    active_agents = state.get("active_agents") or []
    agent_name = active_agents[0] if active_agents else DEFAULT_AGENT_NAME
    try:
        return get_agent(agent_name).folder_path
    except KeyError:
        return get_agent(DEFAULT_AGENT_NAME).folder_path


async def combiner_micro_node(state: GraphState) -> dict[str, Any]:
    """Refine micro data into presentation-ready usable answer segments."""
    micro_data = state.get("micro_data")
    active_agents = state.get("active_agents") or []
    pov_sources = collect_pov_sources(active_agents)

    if micro_data is None:
        logger.warning("Combiner Micro: no micro_data in state")
        trace = AgentTrace(
            agent_name="combiner_micro",
            inputs_seen=[],
            task_summary=state.get("current_task") or None,
            output_preview="No micro data to refine.",
        )
        return {"agent_traces": [trace], "usable_answers": []}

    current_task = state.get("current_task") or state["user_input"]
    segment_count = len(micro_data.segments)

    publish_panel(
        Panel(
            panel_id=state["panel_id"],
            folder_path=_resolve_folder_path(state),
            status="processing",
            content_type="markdown",
            content=f"Refining answer segments ({segment_count} parts)…",
            follow_up_options=[],
            agents_involved=build_agents_involved(state, include_combiners=True),
            agent_traces=state.get("agent_traces", []),
            data_tier="usable",
            pov_sources=pov_sources,
        ),
        state.get("session_id", ""),
    )

    micro_text = serialize_micro_data_for_llm(micro_data)
    user_message = f"Task: {current_task}\n\nMicro data to refine:\n\n{micro_text}"
    defense_notes = (state.get("defense_notes") or "").strip()
    if defense_notes:
        user_message += f"\n\nDefense revision notes (address these):\n{defense_notes}"

    messages: list[LLMMessage] = [
        LLMMessage(role="system", content=COMBINER_MICRO_SYSTEM_PROMPT),
        LLMMessage(role="user", content=user_message),
    ]

    llm_start = time.monotonic()
    llm = create_llm()
    response = await llm.generate(LLMRequest(messages=messages))
    llm_elapsed = time.monotonic() - llm_start
    usable_answers = parse_usable_answers_json(response.content, micro_data)

    logger.info(
        "Combiner Micro completed via %s (%s); segments=%d; llm=%.1fs",
        response.provider,
        response.model,
        len(usable_answers),
        llm_elapsed,
    )

    preview = truncate_preview(
        usable_answers[0].title if usable_answers else "Refinement complete",
        OUTPUT_PREVIEW_MAX_CHARS,
    )
    trace = AgentTrace(
        agent_name="combiner_micro",
        inputs_seen=[
            f"micro_data ({len(micro_data.segments)} segments)",
            f"source_agents ({', '.join(micro_data.source_agents)})",
        ],
        task_summary=current_task,
        output_preview=preview,
    )

    intermediate_panel = Panel(
        panel_id=state["panel_id"],
        folder_path=_resolve_folder_path(state),
        status="processing",
        content_type="markdown",
        content=f"Refined {len(usable_answers)} answer segments…",
        follow_up_options=[],
        agents_involved=build_agents_involved(state, include_combiners=True),
        agent_traces=[*state.get("agent_traces", []), trace],
        data_tier="usable",
        pov_sources=pov_sources,
    )

    result: dict[str, Any] = {
        "usable_answers": usable_answers,
        "agent_traces": [trace],
        "panels": [intermediate_panel],
    }

    if defense_notes:
        result["defense_retry_count"] = (state.get("defense_retry_count") or 0) + 1

    return result
