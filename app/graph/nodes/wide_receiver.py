import logging
from typing import Any

from app.graph.prompts import WIDE_RECEIVER_SYSTEM_PROMPT
from app.graph.state import GraphState
from app.llm.factory import create_llm
from app.llm.types import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)


async def wide_receiver_node(state: GraphState) -> dict[str, Any]:
    """Analyze user input via the configured LLM and seed state for downstream nodes."""
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

    logger.info(
        "Wide Receiver completed via %s (%s)",
        response.provider,
        response.model,
    )

    return {
        "current_task": user_input,
        "active_agents": [],
        "collected_data": [response.content],
    }
