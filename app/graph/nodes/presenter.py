from typing import Any

from app.agents.registry import DEFAULT_AGENT_NAME, format_agent_display_name, get_agent
from app.graph.schemas import DEFAULT_FOLLOW_UP_OPTIONS, AgentTrace, MayorData, Panel
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


def _order_mayor_data(
    mayor_data: list[MayorData],
    active_agents: list[str],
) -> list[MayorData]:
    """Order mayor data entries by active_agents routing order."""
    by_agent = {entry.source_agent: entry for entry in mayor_data}
    ordered: list[MayorData] = []
    for agent in active_agents:
        if agent in by_agent:
            ordered.append(by_agent[agent])
    for entry in mayor_data:
        if entry not in ordered:
            ordered.append(entry)
    return ordered


def _format_mayor_data(mayor_data: list[MayorData], active_agents: list[str]) -> str:
    """Turn mayor data entries into markdown content for the Panel."""
    if not mayor_data:
        return "No response generated."

    ordered = _order_mayor_data(mayor_data, active_agents)

    if len(ordered) == 1:
        return ordered[0].content

    sections: list[str] = []
    for entry in ordered:
        display = format_agent_display_name(entry.source_agent)
        sections.append(f"## {display}\n\n{entry.content}")
    return "\n\n".join(sections)


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
    specialist_names = [
        format_agent_display_name(name)
        for name in active_agents
    ] or [format_agent_display_name(DEFAULT_AGENT_NAME)]
    return ["Wide Receiver", *specialist_names, "Presenter"]


def presenter_node(state: GraphState) -> dict[str, Any]:
    """Format collected data into a strictly typed Panel for frontend streaming."""
    mayor_data = state.get("mayor_data") or []
    collected_data = state["collected_data"]
    active_agents = state.get("active_agents") or []

    if mayor_data:
        content = _format_mayor_data(mayor_data, active_agents)
    else:
        content = _format_collected_data(collected_data)

    presenter_trace = AgentTrace(
        agent_name="presenter",
        inputs_seen=[
            f"mayor_data ({len(mayor_data)} entries)",
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
