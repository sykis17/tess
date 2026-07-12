"""Phase 19 — LLM-generated follow-up suggestion utilities."""

import json
import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.registry import format_agent_display_name
from app.graph.combiner_utils import _extract_json_payload
from app.graph.prompts import FOLLOW_UP_SYSTEM_PROMPT
from app.graph.schemas import DEFAULT_FOLLOW_UP_OPTIONS, PanelSegment
from app.llm.factory import create_llm
from app.llm.types import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)

FollowUpKind = Literal["related", "deviating", "choice", "drill_down"]

_HEADING_PATTERN = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_SUBHEADING_PATTERN = re.compile(r"^###\s+(.+)$", re.MULTILINE)

_SKIP_HEADINGS = frozenset({"sources", "collected data", "references"})

MAX_LABEL_CHARS = 40
EXPECTED_SUGGESTION_COUNT = 4


class FollowUpSuggestion(BaseModel):
    """A single follow-up chip suggestion from the LLM generator."""

    label: str = Field(max_length=MAX_LABEL_CHARS)
    kind: FollowUpKind
    prompt: str | None = None


def _truncate_label(label: str) -> str:
    trimmed = label.strip()
    if len(trimmed) <= MAX_LABEL_CHARS:
        return trimmed
    return trimmed[: MAX_LABEL_CHARS - 1].rstrip() + "…"


def _serialize_pov_segments(segments: list[PanelSegment]) -> str:
    if not segments:
        return "(none)"
    blocks: list[str] = []
    for segment in segments:
        pov = f" [{segment.pov}]" if segment.pov else ""
        blocks.append(f"- {segment.title}{pov}: {segment.content[:200]}")
    return "\n".join(blocks)


def _is_skip_drill_heading(heading: str, active_agents: list[str]) -> bool:
    normalized = heading.strip()
    if normalized.lower() in _SKIP_HEADINGS:
        return True
    for agent in active_agents:
        if normalized == agent or normalized == format_agent_display_name(agent):
            return True
    return False


def _extract_topic_headings(content: str, active_agents: list[str]) -> list[str]:
    """Collect substantive topic headings, skipping agent-name section labels."""
    topics: list[str] = []
    seen: set[str] = set()
    for pattern in (_SUBHEADING_PATTERN, _HEADING_PATTERN):
        for match in pattern.finditer(content):
            heading = match.group(1).strip()
            if _is_skip_drill_heading(heading, active_agents):
                continue
            key = heading.lower()
            if key in seen:
                continue
            seen.add(key)
            topics.append(heading)
    return topics


def _extract_first_heading(content: str, active_agents: list[str] | None = None) -> str | None:
    agents = active_agents or []
    topics = _extract_topic_headings(content, agents)
    if topics:
        return topics[0]
    return None


def build_fallback_follow_ups(
    pov_segments: list[PanelSegment],
    content: str,
    active_agents: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Return follow-up labels with topic-aware chips when LLM generation fails."""
    agents = active_agents or []

    if pov_segments:
        drill_title = pov_segments[0].title
        return (
            [
                _truncate_label(f"Tell me more about {drill_title}"),
                _truncate_label("Who is the target audience?"),
                _truncate_label("Compare to an adjacent topic"),
                _truncate_label("Give a practical next step"),
            ],
            ["drill_down", "related", "deviating", "choice"],
        )

    topics = _extract_topic_headings(content, agents)
    if len(topics) >= 2:
        return (
            [
                _truncate_label(f"Tell me more about {topics[0]}"),
                _truncate_label(f"Clarify scope for {topics[0]}"),
                _truncate_label(f"Compare {topics[0]} and {topics[1]}"),
                _truncate_label("Summarize practical next steps"),
            ],
            ["drill_down", "related", "deviating", "choice"],
        )

    if len(topics) == 1:
        topic = topics[0]
        labels = list(DEFAULT_FOLLOW_UP_OPTIONS)
        kinds: list[str] = ["choice", "choice", "choice"]
        drill_label = _truncate_label(f"Tell me more about {topic}")
        if drill_label not in labels:
            labels[0] = drill_label
            kinds[0] = "drill_down"
        return labels, kinds

    labels = list(DEFAULT_FOLLOW_UP_OPTIONS)
    kinds = ["choice", "choice", "choice"]
    drill_title = _extract_first_heading(content, agents)
    if drill_title:
        drill_label = _truncate_label(f"Tell me more about {drill_title}")
        if drill_label not in labels:
            labels.append(drill_label)
            kinds.append("drill_down")
    return labels, kinds


def parse_follow_up_json(raw: str) -> list[FollowUpSuggestion]:
    """Parse LLM JSON into follow-up suggestions; raises on invalid structure."""
    payload = _extract_json_payload(raw)
    data = json.loads(payload)

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and "suggestions" in data:
        items = data["suggestions"]
    else:
        raise ValueError("Follow-up JSON must be an array or object with 'suggestions'")

    suggestions: list[FollowUpSuggestion] = []
    for item in items:
        suggestion = FollowUpSuggestion.model_validate(item)
        suggestions.append(
            suggestion.model_copy(update={"label": _truncate_label(suggestion.label)})
        )

    if not suggestions:
        raise ValueError("Follow-up JSON contained no suggestions")

    return suggestions


def _suggestions_to_labels_and_kinds(
    suggestions: list[FollowUpSuggestion],
) -> tuple[list[str], list[str]]:
    labels: list[str] = []
    kinds: list[str] = []
    seen: set[str] = set()
    for suggestion in suggestions[:EXPECTED_SUGGESTION_COUNT]:
        label = _truncate_label(suggestion.label)
        if label in seen:
            continue
        seen.add(label)
        labels.append(label)
        kinds.append(suggestion.kind)
    return labels, kinds


async def generate_follow_up_options(
    content: str,
    pov_segments: list[PanelSegment],
    product_mode: str | None,
    active_agents: list[str],
    user_input: str,
) -> tuple[list[str], list[str]]:
    """Return 3–4 short chip labels and parallel kinds; fallback on error."""
    agent_names = ", ".join(format_agent_display_name(a) for a in active_agents) or "none"
    mode = product_mode or "auto"

    user_parts = [
        f"User request: {user_input}",
        f"Product mode: {mode}",
        f"Active agents: {agent_names}",
        f"\nCompleted answer:\n{content[:3000]}",
        f"\nPOV segments:\n{_serialize_pov_segments(pov_segments)}",
    ]

    messages: list[LLMMessage] = [
        LLMMessage(role="system", content=FOLLOW_UP_SYSTEM_PROMPT),
        LLMMessage(role="user", content="\n".join(user_parts)),
    ]

    try:
        llm = create_llm()
        response = await llm.generate(LLMRequest(messages=messages))
        suggestions = parse_follow_up_json(response.content)
        labels, kinds = _suggestions_to_labels_and_kinds(suggestions)
        if labels:
            return labels, kinds
    except Exception as exc:
        logger.warning("Follow-up generation failed, using fallback: %s", exc)

    return build_fallback_follow_ups(pov_segments, content, active_agents)
