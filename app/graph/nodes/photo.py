from typing import Any

from app.agents.base import run_specialist
from app.graph.state import GraphState


async def photo_node(state: GraphState) -> dict[str, Any]:
    """Run the Photo specialist agent."""
    return await run_specialist(state, "photo")
