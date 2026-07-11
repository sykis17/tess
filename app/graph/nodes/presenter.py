from typing import Any

from app.agents.registry import DEFAULT_AGENT_NAME, format_agent_display_name, get_agent
from app.graph.schemas import DEFAULT_FOLLOW_UP_OPTIONS, AgentTrace, MayorData, Panel
from app.graph.state import GraphState

RESOURCE_READER_AGENT = "resource_reader"


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
    """Order mayor data entries by active_agents routing order; sources last."""
    by_agent = {entry.source_agent: entry for entry in mayor_data}
    ordered: list[MayorData] = []
    for agent in active_agents:
        if agent in by_agent:
            ordered.append(by_agent[agent])
    for entry in mayor_data:
        if entry.source_agent == RESOURCE_READER_AGENT:
            if entry not in ordered:
                ordered.append(entry)
        elif entry not in ordered:
            ordered.append(entry)
    return ordered


def _split_specialist_and_sources(
    mayor_data: list[MayorData],
    active_agents: list[str],
) -> tuple[list[MayorData], MayorData | None]:
    """Separate specialist mayor data from resource reader sources."""
    ordered = _order_mayor_data(mayor_data, active_agents)
    specialists = [e for e in ordered if e.source_agent != RESOURCE_READER_AGENT]
    sources = next((e for e in ordered if e.source_agent == RESOURCE_READER_AGENT), None)
    return specialists, sources


def _format_specialist_sections(specialists: list[MayorData]) -> str:
    """Format specialist mayor data into markdown sections."""
    if not specialists:
        return ""

    if len(specialists) == 1:
        return specialists[0].content

    sections: list[str] = []
    for entry in specialists:
        display = format_agent_display_name(entry.source_agent)
        sections.append(f"## {display}\n\n{entry.content}")
    return "\n\n".join(sections)


def _format_sources_section(sources: MayorData) -> str:
    """Format resource reader output into a Sources section."""
    lines = ["## Sources", "", sources.content]
    if sources.citations:
        lines.extend(["", "**References:**"])
        lines.extend(f"- {citation}" for citation in sources.citations)
    return "\n".join(lines)


def _format_mayor_data(mayor_data: list[MayorData], active_agents: list[str]) -> str:
    """Turn mayor data entries into markdown content for the Panel."""
    if not mayor_data:
        return "No response generated."

    specialists, sources = _split_specialist_and_sources(mayor_data, active_agents)
    parts: list[str] = []

    specialist_content = _format_specialist_sections(specialists)
    if specialist_content:
        parts.append(specialist_content)

    if sources:
        parts.append(_format_sources_section(sources))

    return "\n\n".join(parts) if parts else "No response generated."


def _resolve_folder_path(state: GraphState) -> str:
    """Resolve the Panel folder path from the active specialist agent."""
    active_agents = state.get("active_agents") or []
    agent_name = active_agents[0] if active_agents else DEFAULT_AGENT_NAME

    try:
        return get_agent(agent_name).folder_path
    except KeyError:
        return get_agent(DEFAULT_AGENT_NAME).folder_path


def _search_ran(state: GraphState) -> bool:
    """Return True when the search pipeline was triggered for this message."""
    if state.get("search_queries"):
        return True
    mayor_data = state.get("mayor_data") or []
    return any(entry.source_agent == RESOURCE_READER_AGENT for entry in mayor_data)


def _build_agents_involved(state: GraphState) -> list[str]:
    """Build the human-readable agent pipeline for the Panel."""
    active_agents = state.get("active_agents") or []
    specialist_names = [
        format_agent_display_name(name)
        for name in active_agents
    ] or [format_agent_display_name(DEFAULT_AGENT_NAME)]

    pipeline = ["Wide Receiver", *specialist_names]
    if _search_ran(state):
        pipeline.extend(["Resource Finder", "Resource Reader"])
    pipeline.append("Presenter")
    return pipeline


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
            f"search_queries ({len(state.get('search_queries') or [])})",
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
