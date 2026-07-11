from typing import Any

from app.agents.base import run_specialist
from app.graph.state import GraphState


async def general_assistant_node(state: GraphState) -> dict[str, Any]:
    """Run the General Assistant specialist agent."""
    return await run_specialist(state, "general_assistant")
