from typing import Any

from app.agents.registry import DEFAULT_AGENT_NAME, format_agent_display_name, get_agent
from app.graph.schemas import DEFAULT_FOLLOW_UP_OPTIONS, AgentTrace, Panel
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


def _build_agents_involved(state: GraphState) -> list[str]:
    """Build the human-readable agent pipeline for the Panel."""
    active_agents = state.get("active_agents") or []
    specialist_name = active_agents[0] if active_agents else DEFAULT_AGENT_NAME
    return [
        "Wide Receiver",
        format_agent_display_name(specialist_name),
        "Presenter",
    ]


def presenter_node(state: GraphState) -> dict[str, Any]:
    """Format collected data into a strictly typed Panel for frontend streaming."""
    collected_data = state["collected_data"]
    content = _format_collected_data(collected_data)
    active_agents = state.get("active_agents") or []

    presenter_trace = AgentTrace(
        agent_name="presenter",
        inputs_seen=[
            f"collected_data ({len(collected_data)} entries)",
            f"active_agents ({', '.join(active_agents) if active_agents else 'none'})",
        ],
        task_summary=state.get("current_task") or None,
        output_preview="Formatted specialist output into Panel JSON.",
    )

    panel = Panel(
        panel_id=state["panel_id"],
        folder_path=_resolve_folder_path(state),
        status="completed",
        content_type="markdown",
        content=content,
        follow_up_options=list(DEFAULT_FOLLOW_UP_OPTIONS),
        agents_involved=_build_agents_involved(state),
        agent_traces=[*state.get("agent_traces", []), presenter_trace],
    )

    return {
        "agent_traces": [presenter_trace],
        "panels": [panel],
    }
