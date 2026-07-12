from typing import Any

from app.agents.base import run_specialist
from app.graph.state import GraphState


async def video_node(state: GraphState) -> dict[str, Any]:
    """Run the Video specialist agent."""
    return await run_specialist(state, "video")
