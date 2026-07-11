import logging
from typing import Any

from app.agents.registry import format_agent_display_name, get_agent
from app.graph.prompts import WIDE_RECEIVER_SYSTEM_PROMPT
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


def _format_routing_message(agent_names: list[str]) -> str:
    """Build the processing Panel content for one or more alarmed agents."""
    display_names = [format_agent_display_name(name) for name in agent_names]
    if len(display_names) == 1:
        return f"Routing to {display_names[0]}…"
    return f"Routing to {' + '.join(display_names)}…"


async def wide_receiver_node(state: GraphState) -> dict[str, Any]:
    """Analyze user input and produce a routing decision for specialist agents."""
    user_input = state["user_input"]
    conversation_history = state["conversation_history"]
    logger.info("Wide Receiver received user input: %s", user_input)

    messages: list[LLMMessage] = [
        LLMMessage(role="system", content=WIDE_RECEIVER_SYSTEM_PROMPT),
        *conversation_history,
        LLMMessage(role="user", content=user_input),
    ]

    llm = create_llm()
    response = await llm.generate(LLMRequest(messages=messages))
    decision = parse_routing_decision(response.content, fallback_task=user_input)

    logger.info(
        "Wide Receiver routed to %s via %s (%s); task=%s",
        decision.active_agents,
        response.provider,
        response.model,
        decision.current_task,
    )

    routed_agents = decision.active_agents
    routed_display = ", ".join(routed_agents)
    turn_count = conversation_turn_count(conversation_history)

    wr_trace = AgentTrace(
        agent_name="wide_receiver",
        inputs_seen=["user_input", format_history_input(turn_count)],
        task_summary=decision.current_task,
        output_preview=f"Routed to: {routed_display} — {decision.current_task}",
    )

    agents_involved = [
        "Wide Receiver",
        *[format_agent_display_name(name) for name in routed_agents],
    ]

    processing_panel = Panel(
        panel_id=state["panel_id"],
        folder_path=_resolve_folder_path_for_agent(routed_agents[0]),
        status="processing",
        content_type="markdown",
        content=_format_routing_message(routed_agents),
        follow_up_options=[],
        agents_involved=agents_involved,
        agent_traces=[wr_trace],
    )

    return {
        "current_task": decision.current_task,
        "active_agents": decision.active_agents,
        "agent_traces": [wr_trace],
        "panels": [processing_panel],
    }
