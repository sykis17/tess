from typing import Any

from app.agents.registry import DEFAULT_AGENT_NAME, format_agent_display_name, get_agent
from app.agents.subjects.registry import collect_pov_sources
from app.graph.combiner_utils import (
    format_usable_answers_markdown,
    order_mayor_data,
)
from app.graph.defense_utils import (
    build_agents_involved_with_defense,
    defense_exhausted_retries,
)
from app.graph.media_utils import extract_typed_media_content, resolve_content_type
from app.graph.schemas import (
    DEFAULT_FOLLOW_UP_OPTIONS,
    AgentTrace,
    ContentType,
    MayorData,
    Panel,
)
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


def _resolve_panel_output(
    usable_answers: list,
    mayor_data: list[MayorData],
    collected_data: list[str],
    active_agents: list[str],
    defense_ran: bool,
    exhausted: bool,
) -> tuple[str, ContentType]:
    """Resolve Panel content and content_type from graph state."""
    content_type: ContentType = "markdown"

    if usable_answers:
        if defense_ran and not exhausted:
            approved = [answer for answer in usable_answers if answer.review_status == "approved"]
            content = format_usable_answers_markdown(approved or usable_answers)
        elif defense_ran and exhausted:
            best_effort = [
                answer.model_copy(update={"review_status": "approved"})
                for answer in usable_answers
            ]
            content = format_usable_answers_markdown(best_effort)
        else:
            content = format_usable_answers_markdown(usable_answers)
        return content, content_type

    if mayor_data:
        specialists, sources = _split_specialist_and_sources(mayor_data, active_agents)
        if len(specialists) == 1 and not sources:
            entry = specialists[0]
            content_type = resolve_content_type(entry.source_agent, entry.content)
            content = extract_typed_media_content(entry.content, content_type)
            return content, content_type
        content = _format_mayor_data(mayor_data, active_agents)
        return content, content_type

    content = _format_collected_data(collected_data)
    return content, content_type


def presenter_node(state: GraphState) -> dict[str, Any]:
    """Format collected or synthesized data into a strictly typed Panel for frontend streaming."""
    usable_answers = state.get("usable_answers") or []
    mayor_data = state.get("mayor_data") or []
    collected_data = state["collected_data"]
    active_agents = state.get("active_agents") or []
    combiners_bypassed = state.get("combiners_bypassed", True)
    defense_ran = bool(state.get("defense_reviews"))
    exhausted = defense_exhausted_retries(state)

    content, content_type = _resolve_panel_output(
        usable_answers,
        mayor_data,
        collected_data,
        active_agents,
        defense_ran,
        exhausted,
    )

    include_combiners = not combiners_bypassed and bool(usable_answers)
    agents_involved = build_agents_involved_with_defense(
        state,
        include_combiners=include_combiners,
    )

    presenter_trace = AgentTrace(
        agent_name="presenter",
        inputs_seen=[
            f"usable_answers ({len(usable_answers)} segments)",
            f"mayor_data ({len(mayor_data)} entries)",
            f"collected_data ({len(collected_data)} entries)",
            f"combiners_bypassed ({combiners_bypassed})",
            f"defense_reviews ({len(state.get('defense_reviews') or [])})",
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
        content_type=content_type,
        content=content,
        follow_up_options=list(DEFAULT_FOLLOW_UP_OPTIONS),
        agents_involved=agents_involved,
        agent_traces=[*state.get("agent_traces", []), presenter_trace],
        data_tier="final" if usable_answers else None,
        pov_sources=collect_pov_sources(active_agents),
        product_mode=state.get("product_mode") if state.get("product_mode") != "auto" else None,
    )

    return {
        "agent_traces": [presenter_trace],
        "panels": [panel],
    }
