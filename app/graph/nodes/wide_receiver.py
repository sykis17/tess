import logging
from typing import Any

from app.graph.prompts import WIDE_RECEIVER_SYSTEM_PROMPT
from app.graph.routing import parse_routing_decision
from app.graph.state import GraphState
from app.llm.factory import create_llm
from app.llm.types import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)


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

    return {
        "current_task": decision.current_task,
        "active_agents": decision.active_agents,
    }
