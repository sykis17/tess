import logging
from typing import Any

from app.agents.registry import get_agent
from app.graph.schemas import AgentTrace, MayorData, OUTPUT_PREVIEW_MAX_CHARS
from app.graph.state import GraphState
from app.graph.trace_utils import conversation_turn_count, format_history_input, truncate_preview
from app.llm.factory import create_llm
from app.llm.types import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)


def _build_specialist_user_message(state: GraphState) -> str:
    """Build the user message for a specialist from WR routing output."""
    current_task = state["current_task"].strip()
    user_input = state["user_input"].strip()

    if not current_task or current_task == user_input:
        return user_input

    return f"Task: {current_task}\n\nOriginal request: {user_input}"


async def run_specialist(state: GraphState, agent_name: str) -> dict[str, Any]:
    """Execute a specialist agent LLM call and return collected data."""
    agent = get_agent(agent_name)
    conversation_history = state["conversation_history"]
    user_message = _build_specialist_user_message(state)
    turn_count = conversation_turn_count(conversation_history)

    logger.info("Specialist %s handling task: %s", agent_name, state["current_task"])

    messages: list[LLMMessage] = [
        LLMMessage(role="system", content=agent.system_prompt),
        *conversation_history,
        LLMMessage(role="user", content=user_message),
    ]

    llm = create_llm()
    response = await llm.generate(LLMRequest(messages=messages))

    logger.info(
        "Specialist %s completed via %s (%s)",
        agent_name,
        response.provider,
        response.model,
    )

    specialist_trace = AgentTrace(
        agent_name=agent_name,
        inputs_seen=[
            "user_input",
            "current_task",
            format_history_input(turn_count),
        ],
        task_summary=state["current_task"],
        output_preview=truncate_preview(response.content, OUTPUT_PREVIEW_MAX_CHARS),
    )

    mayor_entry = MayorData(
        source_agent=agent_name,
        content=response.content,
        topic=agent.description,
    )

    return {
        "collected_data": [response.content],
        "mayor_data": [mayor_entry],
        "agent_traces": [specialist_trace],
    }
