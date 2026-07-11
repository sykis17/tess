from typing import Any

from app.agents.base import run_specialist
from app.graph.state import GraphState


async def coder_node(state: GraphState) -> dict[str, Any]:
    """Run the Coder specialist agent."""
    return await run_specialist(state, "coder")
