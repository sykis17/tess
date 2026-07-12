import json
import logging
import re
import uuid
from app.agents.registry import format_agent_display_name
from app.graph.schemas import MayorData, MicroData, MicroDataSegment, UsableAnswer
from app.graph.state import GraphState

logger = logging.getLogger(__name__)

RESOURCE_READER_AGENT = "resource_reader"
MAX_USABLE_ANSWERS = 5

_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def _extract_json_payload(raw: str) -> str:
    """Strip markdown fences and surrounding whitespace from an LLM response."""
    stripped = raw.strip()
    match = _JSON_FENCE_PATTERN.search(stripped)
    if match:
        return match.group(1).strip()
    return stripped


def has_resource_reader_entry(mayor_data: list[MayorData]) -> bool:
    """Return True when mayor data includes output from the search reader."""
    return any(entry.source_agent == RESOURCE_READER_AGENT for entry in mayor_data)


def should_bypass_combiners(state: GraphState) -> bool:
    """Skip combiners for single-agent paths and when search did not contribute.

    Uses active_agents count (not raw mayor_data length) so defense retries that
    append a second mayor entry for the same specialist do not trigger combiners.
    """
    mayor_data = state.get("mayor_data") or []
    active_agents = state.get("active_agents") or []
    if has_resource_reader_entry(mayor_data):
        return False
    return len(active_agents) <= 1


def should_predict_combiners(active_agents: list[str], search_queries: list[str]) -> bool:
    """Predict combiner usage for WR processing Panel badges."""
    return len(active_agents) > 1 or bool(search_queries)


def order_mayor_data(
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


def serialize_mayor_data_for_llm(
    mayor_data: list[MayorData],
    active_agents: list[str],
) -> str:
    """Serialize ordered mayor data into a prompt-friendly text block."""
    ordered = order_mayor_data(mayor_data, active_agents)
    blocks: list[str] = []
    for entry in ordered:
        display = format_agent_display_name(entry.source_agent)
        header = f"### {display}"
        if entry.topic:
            header += f" ({entry.topic})"
        block_lines = [header, "", entry.content]
        if entry.citations:
            block_lines.extend(["", "**Citations:**"])
            block_lines.extend(f"- {citation}" for citation in entry.citations)
        blocks.append("\n".join(block_lines))
    return "\n\n---\n\n".join(blocks)


def _fallback_micro_data(mayor_data: list[MayorData], active_agents: list[str]) -> MicroData:
    """Build a single-segment MicroData fallback from raw mayor content."""
    ordered = order_mayor_data(mayor_data, active_agents)
    segments = [
        MicroDataSegment(
            title=format_agent_display_name(entry.source_agent),
            content=entry.content,
        )
        for entry in ordered
    ]
    source_agents = [entry.source_agent for entry in ordered]
    return MicroData(segments=segments, source_agents=source_agents)


def parse_micro_data_json(
    raw: str,
    mayor_data: list[MayorData],
    active_agents: list[str],
) -> MicroData:
    """Parse Combiner Mayor JSON with a safe fallback to raw mayor content."""
    payload = _extract_json_payload(raw)
    try:
        data = json.loads(payload)
        micro = MicroData.model_validate(data)
        if not micro.segments:
            raise ValueError("MicroData has no segments")
        return micro
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Failed to parse MicroData JSON; using fallback: %s", exc)
        return _fallback_micro_data(mayor_data, active_agents)


def _fallback_usable_answers(micro_data: MicroData) -> list[UsableAnswer]:
    """Build usable answers directly from micro data segments."""
    return [
        UsableAnswer(
            segment_id=str(uuid.uuid4()),
            order_hint=index + 1,
            title=segment.title,
            content=segment.content,
        )
        for index, segment in enumerate(micro_data.segments[:MAX_USABLE_ANSWERS])
    ]


def parse_usable_answers_json(raw: str, micro_data: MicroData) -> list[UsableAnswer]:
    """Parse Combiner Micro JSON with a safe fallback from micro data."""
    payload = _extract_json_payload(raw)
    try:
        data = json.loads(payload)
        if isinstance(data, dict) and "usable_answers" in data:
            items = data["usable_answers"]
        elif isinstance(data, list):
            items = data
        else:
            raise ValueError("Expected list or object with usable_answers key")

        answers: list[UsableAnswer] = []
        for index, item in enumerate(items[:MAX_USABLE_ANSWERS]):
            answer = UsableAnswer.model_validate(item)
            if not answer.segment_id:
                answer = answer.model_copy(update={"segment_id": str(uuid.uuid4())})
            if answer.order_hint <= 0:
                answer = answer.model_copy(update={"order_hint": index + 1})
            answers.append(answer)
        if not answers:
            raise ValueError("No usable answers parsed")
        return answers
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Failed to parse UsableAnswer JSON; using fallback: %s", exc)
        return _fallback_usable_answers(micro_data)


def sort_usable_answers(answers: list[UsableAnswer]) -> list[UsableAnswer]:
    """Sort by order_hint and re-number sequentially."""
    sorted_answers = sorted(answers, key=lambda answer: answer.order_hint)
    return [
        answer.model_copy(update={"order_hint": index + 1})
        for index, answer in enumerate(sorted_answers)
    ]


def format_usable_answers_markdown(answers: list[UsableAnswer]) -> str:
    """Turn usable answers into markdown content for the Panel."""
    if not answers:
        return "No response generated."

    ordered = sort_usable_answers(answers)
    if len(ordered) == 1:
        return ordered[0].content

    sections: list[str] = []
    for answer in ordered:
        sections.append(f"## {answer.title}\n\n{answer.content}")
    return "\n\n".join(sections)


def serialize_micro_data_for_llm(micro_data: MicroData) -> str:
    """Serialize micro data into a prompt-friendly text block."""
    blocks: list[str] = []
    for segment in micro_data.segments:
        blocks.append(f"### {segment.title}\n\n{segment.content}")
    return "\n\n---\n\n".join(blocks)


def combiner_pipeline_names() -> list[str]:
    """Human-readable combiner pipeline names for agents_involved."""
    return [
        format_agent_display_name("combiner_mayor"),
        format_agent_display_name("combiner_micro"),
        format_agent_display_name("collector"),
    ]


def build_agents_involved(state: GraphState, *, include_combiners: bool) -> list[str]:
    """Build the human-readable agent pipeline for a Panel."""
    from app.agents.registry import DEFAULT_AGENT_NAME

    active_agents = state.get("active_agents") or []
    specialist_names = [
        format_agent_display_name(name)
        for name in active_agents
    ] or [format_agent_display_name(DEFAULT_AGENT_NAME)]

    pipeline = ["Wide Receiver", *specialist_names]
    if state.get("search_queries") or has_resource_reader_entry(state.get("mayor_data") or []):
        pipeline.extend([
            format_agent_display_name("resource_finder"),
            format_agent_display_name("resource_reader"),
        ])
    if include_combiners:
        pipeline.extend(combiner_pipeline_names())
    pipeline.append(format_agent_display_name("presenter"))
    return pipeline
