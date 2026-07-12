import logging
from typing import Any

from app.agents.registry import format_agent_display_name, get_agent
from app.agents.subjects.registry import collect_pov_sources
from app.graph.combiner_utils import combiner_pipeline_names, should_predict_combiners
from app.graph.defense_utils import defense_pipeline_names, should_predict_defense
from app.graph.fan_in_utils import build_expected_fan_in_branches
from app.graph.prompts import build_wr_system_prompt
from app.graph.routing import parse_routing_decision
from app.graph.schemas import AgentTrace, Panel
from app.graph.state import GraphState
from app.graph.trace_utils import conversation_turn_count, format_history_input, truncate_preview
from app.llm.factory import create_llm
from app.llm.types import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)


def _resolve_folder_path_for_agent(agent_name: str) -> str:
    try:
        return get_agent(agent_name).folder_path
    except KeyError:
        from app.agents.registry import DEFAULT_AGENT_NAME

        return get_agent(DEFAULT_AGENT_NAME).folder_path


def _format_routing_message(
    agent_names: list[str],
    search_queries: list[str] | None = None,
) -> str:
    """Build the processing Panel content for one or more alarmed agents."""
    display_names = [format_agent_display_name(name) for name in agent_names]
    if search_queries:
        display_names.append("Resource Finder")
    if len(display_names) == 1:
        return f"Routing to {display_names[0]}…"
    return f"Routing to {' + '.join(display_names)}…"


async def wide_receiver_node(state: GraphState) -> dict[str, Any]:
    """Analyze user input and produce a routing decision for specialist agents."""
    user_input = state["user_input"]
    conversation_history = state["conversation_history"]
    product_mode = state.get("product_mode", "auto")
    logger.info("Wide Receiver received user input: %s (mode=%s)", user_input, product_mode)

    system_prompt = build_wr_system_prompt(product_mode)
    messages: list[LLMMessage] = [
        LLMMessage(role="system", content=system_prompt),
        *conversation_history,
        LLMMessage(role="user", content=user_input),
    ]

    llm = create_llm()
    response = await llm.generate(LLMRequest(messages=messages))
    decision = parse_routing_decision(
        response.content,
        fallback_task=user_input,
        product_mode=product_mode,
    )

    logger.info(
        "Wide Receiver routed to %s via %s (%s); task=%s",
        decision.active_agents,
        response.provider,
        response.model,
        decision.current_task,
    )

    routed_agents = decision.active_agents
    search_queries = decision.search_queries
    routed_display = ", ".join(routed_agents)
    turn_count = conversation_turn_count(conversation_history)

    preview_parts = [f"Routed to: {routed_display} — {decision.current_task}"]
    if search_queries:
        preview_parts.append(f"Search: {search_queries[0]}")

    wr_trace = AgentTrace(
        agent_name="wide_receiver",
        inputs_seen=["user_input", format_history_input(turn_count)],
        task_summary=decision.current_task,
        output_preview=" | ".join(preview_parts),
    )

    agents_involved = [
        "Wide Receiver",
        *[format_agent_display_name(name) for name in routed_agents],
    ]
    if search_queries:
        agents_involved.append("Resource Finder")
    if should_predict_combiners(routed_agents, search_queries):
        agents_involved.extend(combiner_pipeline_names())
    if should_predict_defense(routed_agents, search_queries):
        agents_involved.extend(defense_pipeline_names())

    processing_panel = Panel(
        panel_id=state["panel_id"],
        folder_path=_resolve_folder_path_for_agent(routed_agents[0]),
        status="processing",
        content_type="markdown",
        content=_format_routing_message(routed_agents, search_queries),
        follow_up_options=[],
        agents_involved=agents_involved,
        agent_traces=[wr_trace],
        pov_sources=collect_pov_sources(routed_agents),
        product_mode=product_mode if product_mode != "auto" else None,
    )

    return {
        "current_task": decision.current_task,
        "active_agents": decision.active_agents,
        "search_queries": search_queries,
        "expected_fan_in_branches": build_expected_fan_in_branches(
            decision.active_agents,
            search_queries,
        ),
        "agent_traces": [wr_trace],
        "panels": [processing_panel],
    }
