import uuid
from typing import Any

from app.agents.registry import DEFAULT_AGENT_NAME, get_agent
from app.graph.schemas import DEFAULT_FOLLOW_UP_OPTIONS, Panel
from app.graph.state import GraphState


def _format_collected_data(collected_data: list[str]) -> str:
    """Turn collected data entries into markdown content for the Panel."""
    if not collected_data:
        return "No response generated."

    if len(collected_data) == 1:
        return collected_data[0]

    lines = ["## Collected Data", ""]
    lines.extend(f"- {entry}" for entry in collected_data)
    return "\n".join(lines)


def _resolve_folder_path(state: GraphState) -> str:
    """Resolve the Panel folder path from the active specialist agent."""
    active_agents = state.get("active_agents") or []
    agent_name = active_agents[0] if active_agents else DEFAULT_AGENT_NAME

    try:
        return get_agent(agent_name).folder_path
    except KeyError:
        return get_agent(DEFAULT_AGENT_NAME).folder_path


def presenter_node(state: GraphState) -> dict[str, Any]:
    """Format collected data into a strictly typed Panel for frontend streaming."""
    collected_data = state["collected_data"]
    content = _format_collected_data(collected_data)

    panel = Panel(
        panel_id=str(uuid.uuid4()),
        folder_path=_resolve_folder_path(state),
        status="completed",
        content_type="markdown",
        content=content,
        follow_up_options=list(DEFAULT_FOLLOW_UP_OPTIONS),
    )

    return {"panels": [panel]}
