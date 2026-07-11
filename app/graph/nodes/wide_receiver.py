import logging
from typing import Any

from app.graph.state import GraphState

logger = logging.getLogger(__name__)


def wide_receiver_node(state: GraphState) -> dict[str, Any]:
    """Analyze user input and seed the graph state for downstream nodes."""
    user_input = state["user_input"]
    logger.info("Wide Receiver received user input: %s", user_input)

    return {
        "current_task": user_input,
        "active_agents": [],
        "collected_data": [f"Task analyzed: {user_input}"],
    }
