"""Build structured POV segments for completed Panels."""

from app.agents.registry import format_agent_display_name
from app.agents.subjects.registry import collect_pov_sources
from app.graph.combiner_utils import RESOURCE_READER_AGENT, order_mayor_data, sort_usable_answers
from app.graph.schemas import MayorData, PanelSegment, UsableAnswer


def _pov_label_for_agents(source_agents: list[str]) -> str | None:
    """Map source agent keys to a display POV label."""
    labels = collect_pov_sources(source_agents)
    if not labels:
        return None
    if len(labels) == 1:
        return labels[0]
    return " + ".join(labels)


def _filter_usable_answers_for_segments(
    usable_answers: list[UsableAnswer],
    defense_ran: bool,
    exhausted: bool,
) -> list[UsableAnswer]:
    """Mirror presenter approval filtering for segment building."""
    if not usable_answers:
        return []

    if defense_ran and not exhausted:
        approved = [a for a in usable_answers if a.review_status == "approved"]
        return sort_usable_answers(approved or usable_answers)

    if defense_ran and exhausted:
        return sort_usable_answers(usable_answers)

    return sort_usable_answers(usable_answers)


def _segments_from_usable_answers(
    usable_answers: list[UsableAnswer],
    defense_ran: bool,
    exhausted: bool,
) -> list[PanelSegment]:
    filtered = _filter_usable_answers_for_segments(usable_answers, defense_ran, exhausted)
    segments: list[PanelSegment] = []
    for answer in filtered:
        if answer.title == "Sources":
            continue
        segments.append(
            PanelSegment(
                title=answer.title,
                content=answer.content,
                source_agents=list(answer.source_agents),
                pov=_pov_label_for_agents(answer.source_agents),
            )
        )
    return segments


def _split_specialist_and_sources(
    mayor_data: list[MayorData],
    active_agents: list[str],
) -> tuple[list[MayorData], MayorData | None]:
    ordered = order_mayor_data(mayor_data, active_agents)
    specialists = [e for e in ordered if e.source_agent != RESOURCE_READER_AGENT]
    sources = next((e for e in ordered if e.source_agent == RESOURCE_READER_AGENT), None)
    return specialists, sources


def _segments_from_mayor_data(
    mayor_data: list[MayorData],
    active_agents: list[str],
) -> list[PanelSegment]:
    specialists, _sources = _split_specialist_and_sources(mayor_data, active_agents)
    if len(specialists) <= 1:
        return []

    segments: list[PanelSegment] = []
    for entry in specialists:
        title = entry.pov or format_agent_display_name(entry.source_agent)
        segments.append(
            PanelSegment(
                title=title,
                content=entry.content,
                source_agents=[entry.source_agent],
                pov=entry.pov,
            )
        )
    return segments


def _count_specialists(active_agents: list[str]) -> int:
    return sum(1 for name in active_agents if name != RESOURCE_READER_AGENT)


def _is_single_lens_run(active_agents: list[str]) -> bool:
    """True when the panel has at most one specialist and fewer than two POV lenses."""
    return (
        len(collect_pov_sources(active_agents)) < 2
        and _count_specialists(active_agents) <= 1
    )


def _distinct_povs_in_segments(segments: list[PanelSegment]) -> set[str]:
    """Collect POV display labels represented across segments."""
    povs: set[str] = set()
    for segment in segments:
        if segment.pov:
            if " + " in segment.pov:
                povs.update(part.strip() for part in segment.pov.split(" + "))
            else:
                povs.add(segment.pov)
        povs.update(collect_pov_sources(segment.source_agents))
    return povs


def _segments_share_single_lens(segments: list[PanelSegment]) -> bool:
    """True when multiple segments all map to the same POV or source agent."""
    if len(segments) <= 1:
        return False
    source_sets = {tuple(sorted(segment.source_agents)) for segment in segments}
    if len(source_sets) == 1:
        return True
    povs = {segment.pov for segment in segments if segment.pov}
    return len(povs) == 1


def _segments_cover_multiple_povs(
    segments: list[PanelSegment],
    active_agents: list[str],
) -> bool:
    """True when segments reflect at least two routed POV lenses."""
    expected = collect_pov_sources(active_agents)
    if len(expected) < 2:
        return False
    found = _distinct_povs_in_segments(segments)
    return len(found.intersection(expected)) >= 2


def build_pov_segments(
    usable_answers: list[UsableAnswer],
    mayor_data: list[MayorData],
    active_agents: list[str],
    defense_ran: bool,
    exhausted: bool,
) -> list[PanelSegment]:
    """Build structured per-lens segments for a completed Panel."""
    if _is_single_lens_run(active_agents):
        return []

    is_multi_pov = len(collect_pov_sources(active_agents)) >= 2

    if usable_answers:
        segments = _segments_from_usable_answers(usable_answers, defense_ran, exhausted)
        if (
            len(segments) > 1
            and not _segments_share_single_lens(segments)
            and _segments_cover_multiple_povs(segments, active_agents)
        ):
            return segments
        if is_multi_pov:
            mayor_segments = _segments_from_mayor_data(mayor_data, active_agents)
            if mayor_segments:
                return mayor_segments
        return []

    if is_multi_pov:
        return _segments_from_mayor_data(mayor_data, active_agents)

    return []
