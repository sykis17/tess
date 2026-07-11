import uuid
from typing import Any

from app.graph.schemas import DEFAULT_FOLLOW_UP_OPTIONS, Panel
from app.graph.state import GraphState

DEFAULT_FOLDER_PATH = "Assistant/Chat"


def _format_collected_data(collected_data: list[str]) -> str:
    """Turn collected data entries into markdown content for the Panel."""
    if not collected_data:
        return "No response generated."

    if len(collected_data) == 1:
        return collected_data[0]

    lines = ["## Collected Data", ""]
    lines.extend(f"- {entry}" for entry in collected_data)
    return "\n".join(lines)


def presenter_node(state: GraphState) -> dict[str, Any]:
    """Format collected data into a strictly typed Panel for frontend streaming."""
    collected_data = state["collected_data"]
    content = _format_collected_data(collected_data)

    panel = Panel(
        panel_id=str(uuid.uuid4()),
        folder_path=DEFAULT_FOLDER_PATH,
        status="completed",
        content_type="markdown",
        content=content,
        follow_up_options=list(DEFAULT_FOLLOW_UP_OPTIONS),
    )

    return {"panels": [panel]}
