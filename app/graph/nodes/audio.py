from typing import Any

from app.agents.base import run_specialist
from app.graph.state import GraphState


async def audio_node(state: GraphState) -> dict[str, Any]:
    """Run the Audio specialist agent."""
    return await run_specialist(state, "audio")
