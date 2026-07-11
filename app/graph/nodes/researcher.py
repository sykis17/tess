from typing import Any

from app.agents.base import run_specialist
from app.graph.state import GraphState


async def researcher_node(state: GraphState) -> dict[str, Any]:
    """Run the Researcher specialist agent."""
    return await run_specialist(state, "researcher")
