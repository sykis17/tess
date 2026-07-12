import logging
import time
from typing import Any

from app.agents.registry import get_agent, DEFAULT_AGENT_NAME
from app.agents.subjects.registry import collect_pov_sources
from app.graph.combiner_utils import (
    build_agents_involved,
    parse_micro_data_json,
    serialize_mayor_data_for_llm,
)
from app.graph.panel_stream import publish_panel
from app.graph.pipeline_stages import PipelineStage
from app.graph.prompts import build_combiner_mayor_prompt
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


def _synthesis_progress_message(active_agents: list[str]) -> str:
    pov_labels = collect_pov_sources(active_agents)
    if pov_labels:
        return f"Sorting and cataloging {' + '.join(pov_labels)} perspectives…"
    return "Sorting and cataloging specialist perspectives…"


async def combiner_mayor_node(state: GraphState) -> dict[str, Any]:
    """Aggregate all mayor data into cross-topic micro data."""
    mayor_data = state.get("mayor_data") or []
    active_agents = state.get("active_agents") or []
    current_task = state.get("current_task") or state["user_input"]
    user_input = state["user_input"]
    pov_sources = collect_pov_sources(active_agents)

    logger.info("Combiner Mayor synthesizing %d mayor data entries", len(mayor_data))

    publish_panel(
        Panel(
            panel_id=state["panel_id"],
            folder_path=_resolve_folder_path(state),
            status="processing",
            content_type="markdown",
            content=_synthesis_progress_message(active_agents),
            follow_up_options=[],
            agents_involved=build_agents_involved(state, include_combiners=True),
            agent_traces=state.get("agent_traces", []),
            data_tier="micro",
            pov_sources=pov_sources,
            output_level=state.get("chain_profile"),
            pipeline_stage=PipelineStage.COMBINING,
        ),
        state.get("session_id", ""),
    )

    mayor_text = serialize_mayor_data_for_llm(mayor_data, active_agents)
    user_message = (
        f"Task: {current_task}\n\n"
        f"Original request: {user_input}\n\n"
        f"Mayor data from agents:\n\n{mayor_text}"
    )

    product_mode = state.get("product_mode", "auto")
    messages: list[LLMMessage] = [
        LLMMessage(role="system", content=build_combiner_mayor_prompt(product_mode)),
        LLMMessage(role="user", content=user_message),
    ]

    llm_start = time.monotonic()
    llm = create_llm()
    response = await llm.generate(LLMRequest(messages=messages))
    llm_elapsed = time.monotonic() - llm_start
    micro_data = parse_micro_data_json(response.content, mayor_data, active_agents)

    logger.info(
        "Combiner Mayor completed via %s (%s); segments=%d; llm=%.1fs",
        response.provider,
        response.model,
        len(micro_data.segments),
        llm_elapsed,
    )

    preview = truncate_preview(
        micro_data.segments[0].title if micro_data.segments else "Synthesis complete",
        OUTPUT_PREVIEW_MAX_CHARS,
    )
    trace = AgentTrace(
        agent_name="combiner_mayor",
        inputs_seen=[
            f"mayor_data ({len(mayor_data)} entries)",
            f"active_agents ({', '.join(active_agents)})",
            "current_task",
            "user_input",
        ],
        task_summary=current_task,
        output_preview=preview,
    )

    intermediate_panel = Panel(
        panel_id=state["panel_id"],
        folder_path=_resolve_folder_path(state),
        status="processing",
        content_type="markdown",
        content=f"Cataloged {len(micro_data.segments)} sorted themes…",
        follow_up_options=[],
        agents_involved=build_agents_involved(state, include_combiners=True),
        agent_traces=[*state.get("agent_traces", []), trace],
        data_tier="micro",
        pov_sources=pov_sources,
        output_level=state.get("chain_profile"),
        pipeline_stage=PipelineStage.COMBINING,
    )

    return {
        "micro_data": micro_data,
        "agent_traces": [trace],
        "panels": [intermediate_panel],
    }
