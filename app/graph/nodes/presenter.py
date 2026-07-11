from typing import Any

from app.agents.registry import DEFAULT_AGENT_NAME, format_agent_display_name, get_agent
from app.graph.combiner_utils import (
    build_agents_involved,
    format_usable_answers_markdown,
    order_mayor_data,
)
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


def _split_specialist_and_sources(
    mayor_data: list[MayorData],
    active_agents: list[str],
) -> tuple[list[MayorData], MayorData | None]:
    """Separate specialist mayor data from resource reader sources."""
    ordered = order_mayor_data(mayor_data, active_agents)
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
    """Turn mayor data entries into markdown content for the Panel (bypass path)."""
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


def presenter_node(state: GraphState) -> dict[str, Any]:
    """Format collected or synthesized data into a strictly typed Panel for frontend streaming."""
    usable_answers = state.get("usable_answers") or []
    mayor_data = state.get("mayor_data") or []
    collected_data = state["collected_data"]
    active_agents = state.get("active_agents") or []
    combiners_bypassed = state.get("combiners_bypassed", True)

    if usable_answers:
        content = format_usable_answers_markdown(usable_answers)
    elif mayor_data:
        content = _format_mayor_data(mayor_data, active_agents)
    else:
        content = _format_collected_data(collected_data)

    include_combiners = not combiners_bypassed and bool(usable_answers)
    agents_involved = build_agents_involved(state, include_combiners=include_combiners)

    presenter_trace = AgentTrace(
        agent_name="presenter",
        inputs_seen=[
            f"usable_answers ({len(usable_answers)} segments)",
            f"mayor_data ({len(mayor_data)} entries)",
            f"collected_data ({len(collected_data)} entries)",
            f"combiners_bypassed ({combiners_bypassed})",
            f"search_queries ({len(state.get('search_queries') or [])})",
        ],
        task_summary=state.get("current_task") or None,
        output_preview="Formatted synthesized output into Panel JSON."
        if usable_answers
        else "Formatted specialist output into Panel JSON.",
    )

    panel = Panel(
        panel_id=state["panel_id"],
        folder_path=_resolve_folder_path(state),
        status="completed",
        content_type="markdown",
        content=content,
        follow_up_options=list(DEFAULT_FOLLOW_UP_OPTIONS),
        agents_involved=agents_involved,
        agent_traces=[*state.get("agent_traces", []), presenter_trace],
        data_tier="final" if usable_answers else None,
    )

    return {
        "agent_traces": [presenter_trace],
        "panels": [panel],
    }
