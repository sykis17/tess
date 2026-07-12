import json
import logging
import re
import uuid

from app.agents.registry import DEFAULT_AGENT_NAME, format_agent_display_name
from app.graph.combiner_utils import (
    MAX_USABLE_ANSWERS,
    RESOURCE_READER_AGENT,
    build_agents_involved,
    order_mayor_data,
    paragraph_fingerprints,
)
from app.graph.schemas import DefenseChecks, DefenseReview, UsableAnswer
from app.graph.state import GraphState

logger = logging.getLogger(__name__)

MAX_DEFENSE_RETRIES = 2

_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)
_REFUSAL_PATTERNS = (
    re.compile(r"i can'?t help you with that", re.IGNORECASE),
    re.compile(r"i can'?t help with that", re.IGNORECASE),
    re.compile(r"i can'?t assist with that", re.IGNORECASE),
    re.compile(r"i cannot help you", re.IGNORECASE),
    re.compile(r"i'?m not able to help", re.IGNORECASE),
    re.compile(r"i am not able to help", re.IGNORECASE),
    re.compile(r"i'?m unable to help", re.IGNORECASE),
    re.compile(r"as an ai language model, i can'?t", re.IGNORECASE),
)


def _extract_json_payload(raw: str) -> str:
    """Strip markdown fences and surrounding whitespace from an LLM response."""
    stripped = raw.strip()
    match = _JSON_FENCE_PATTERN.search(stripped)
    if match:
        return match.group(1).strip()
    return stripped


def defense_pipeline_names() -> list[str]:
    """Human-readable defense pipeline names for agents_involved."""
    return [
        format_agent_display_name("defense_delegator"),
        format_agent_display_name("defense_review"),
    ]


def should_predict_defense(
    _active_agents: list[str],
    _search_queries: list[str],
    chain_profile: str = "L4",
) -> bool:
    """Predict defense usage for WR processing Panel badges."""
    from app.graph.chain_gates import allows_defense

    return allows_defense(chain_profile)


def normalize_segments_for_review(state: GraphState) -> list[UsableAnswer]:
    """Return usable answers for defense, wrapping mayor data on bypass path."""
    combiners_bypassed = state.get("combiners_bypassed", False)
    usable_answers = state.get("usable_answers") or []
    if usable_answers and not combiners_bypassed:
        return usable_answers[:MAX_USABLE_ANSWERS]

    mayor_data = state.get("mayor_data") or []
    active_agents = state.get("active_agents") or []
    ordered = order_mayor_data(mayor_data, active_agents)

    segments: list[UsableAnswer] = []
    for index, entry in enumerate(ordered):
        if entry.source_agent == RESOURCE_READER_AGENT:
            continue
        segments.append(
            UsableAnswer(
                segment_id=str(uuid.uuid4()),
                order_hint=index + 1,
                title=format_agent_display_name(entry.source_agent),
                content=entry.content,
                review_status="pending",
                source_agents=[entry.source_agent],
            )
        )

    sources = next(
        (entry for entry in ordered if entry.source_agent == RESOURCE_READER_AGENT),
        None,
    )
    if sources:
        segments.append(
            UsableAnswer(
                segment_id=str(uuid.uuid4()),
                order_hint=len(segments) + 1,
                title="Sources",
                content=sources.content,
                review_status="pending",
            )
        )

    return segments[:MAX_USABLE_ANSWERS]


def serialize_segments_for_llm(segments: list[UsableAnswer]) -> str:
    """Serialize answer segments into a prompt-friendly text block."""
    blocks: list[str] = []
    for segment in segments:
        blocks.append(
            f"### Segment {segment.segment_id}\n"
            f"Title: {segment.title}\n\n"
            f"{segment.content}"
        )
    return "\n\n---\n\n".join(blocks)


def _fallback_auto_pass(segments: list[UsableAnswer]) -> list[DefenseReview]:
    """Auto-pass all segments when defense JSON parsing fails."""
    return [
        DefenseReview(
            segment_id=segment.segment_id,
            checks=DefenseChecks(big_picture="pass", detail="pass", implication="pass"),
            notes="Auto-passed due to parse fallback.",
            verdict="pass",
        )
        for segment in segments
    ]


def segment_contains_refusal(content: str) -> bool:
    """Return True when segment content looks like a specialist refusal."""
    normalized = content.strip()
    if len(normalized) > 300:
        return False
    return any(pattern.search(normalized) for pattern in _REFUSAL_PATTERNS)


def _segment_ids_with_cross_repetition(segments: list[UsableAnswer]) -> set[str]:
    """Return segment IDs that repeat substantive paragraphs from earlier segments."""
    seen: dict[str, str] = {}
    repeating: set[str] = set()

    for segment in segments:
        for fingerprint in paragraph_fingerprints(segment.content):
            prior_segment_id = seen.get(fingerprint)
            if prior_segment_id is not None and prior_segment_id != segment.segment_id:
                repeating.add(segment.segment_id)
            else:
                seen[fingerprint] = segment.segment_id
    return repeating


def apply_repetition_overrides(
    segments: list[UsableAnswer],
    reviews: list[DefenseReview],
) -> list[DefenseReview]:
    """Force revise verdicts when segments repeat the same substantive paragraphs."""
    repeating_ids = _segment_ids_with_cross_repetition(segments)
    if not repeating_ids:
        return reviews

    updated: list[DefenseReview] = []
    for review in reviews:
        if review.segment_id not in repeating_ids or review.verdict != "pass":
            updated.append(review)
            continue

        updated.append(
            review.model_copy(
                update={
                    "verdict": "revise",
                    "checks": DefenseChecks(
                        big_picture="revise",
                        detail="pass",
                        implication="pass",
                    ),
                    "notes": review.notes.strip()
                    or "Repeated themes or paragraphs across segments; collapse duplicates and keep 5–7 distinct themes.",
                }
            )
        )
    return updated


def apply_refusal_overrides(
    segments: list[UsableAnswer],
    reviews: list[DefenseReview],
) -> list[DefenseReview]:
    """Force revise verdicts when segment content is a refusal."""
    segment_by_id = {segment.segment_id: segment for segment in segments}
    updated: list[DefenseReview] = []

    for review in reviews:
        segment = segment_by_id.get(review.segment_id)
        if segment is None or not segment_contains_refusal(segment.content):
            updated.append(review)
            continue

        updated.append(
            review.model_copy(
                update={
                    "verdict": "revise",
                    "checks": DefenseChecks(
                        big_picture="revise",
                        detail="revise",
                        implication="revise",
                    ),
                    "notes": review.notes.strip()
                    or "Specialist refused to answer; provide a helpful response to the user's task.",
                }
            )
        )

    return updated


def parse_defense_reviews_json(raw: str, segments: list[UsableAnswer]) -> list[DefenseReview]:
    """Parse Defense Review JSON with a safe fallback to auto-pass."""
    payload = _extract_json_payload(raw)
    segment_ids = {segment.segment_id for segment in segments}

    try:
        data = json.loads(payload)
        if isinstance(data, dict) and "defense_reviews" in data:
            items = data["defense_reviews"]
        elif isinstance(data, list):
            items = data
        else:
            raise ValueError("Expected list or object with defense_reviews key")

        reviews: list[DefenseReview] = []
        seen_ids: set[str] = set()
        for item in items:
            review = DefenseReview.model_validate(item)
            if review.segment_id not in segment_ids:
                logger.warning("Defense review segment_id not found: %s", review.segment_id)
                continue
            seen_ids.add(review.segment_id)
            reviews.append(review)

        for segment in segments:
            if segment.segment_id not in seen_ids:
                reviews.append(
                    DefenseReview(
                        segment_id=segment.segment_id,
                        checks=DefenseChecks(
                            big_picture="pass", detail="pass", implication="pass"
                        ),
                        notes="Missing from defense output; auto-passed.",
                        verdict="pass",
                    )
                )

        if not reviews:
            raise ValueError("No defense reviews parsed")
        return apply_repetition_overrides(segments, apply_refusal_overrides(segments, reviews))
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Failed to parse DefenseReview JSON; using auto-pass fallback: %s", exc)
        fallback = _fallback_auto_pass(segments)
        return apply_repetition_overrides(segments, apply_refusal_overrides(segments, fallback))


def apply_defense_verdicts(
    segments: list[UsableAnswer],
    reviews: list[DefenseReview],
) -> list[UsableAnswer]:
    """Update segment review_status from defense verdicts."""
    review_by_id = {review.segment_id: review for review in reviews}
    updated: list[UsableAnswer] = []

    for segment in segments:
        review = review_by_id.get(segment.segment_id)
        if review is None:
            updated.append(segment.model_copy(update={"review_status": "approved"}))
            continue

        if review.verdict == "pass":
            status = "approved"
        elif review.verdict == "revise":
            status = "revise"
        else:
            status = "revise"

        updated.append(segment.model_copy(update={"review_status": status}))

    return updated


def aggregate_defense_notes(reviews: list[DefenseReview]) -> str:
    """Concatenate revise notes for retry prompt injection."""
    notes: list[str] = []
    for review in reviews:
        if review.verdict != "pass" and review.notes.strip():
            notes.append(f"- [{review.segment_id[:8]}…] {review.notes.strip()}")
    return "\n".join(notes)


def all_segments_approved(reviews: list[DefenseReview]) -> bool:
    """Return True when every defense review verdict is pass."""
    return bool(reviews) and all(review.verdict == "pass" for review in reviews)


def should_retry_defense(state: GraphState, reviews: list[DefenseReview]) -> bool:
    """Return True when defense failed and retries remain."""
    retry_count = state.get("defense_retry_count") or 0
    return not all_segments_approved(reviews) and retry_count < MAX_DEFENSE_RETRIES


def defense_exhausted_retries(state: GraphState) -> bool:
    """Return True when max defense retries have been reached."""
    retry_count = state.get("defense_retry_count") or 0
    return retry_count >= MAX_DEFENSE_RETRIES


def format_review_passed_content(reviews: list[DefenseReview]) -> str:
    """Build the review_passed Panel content message."""
    passed = sum(1 for review in reviews if review.verdict == "pass")
    total = len(reviews)
    if passed == total:
        return f"Quality checks passed ({passed}/{total}) — formatting final answer…"
    return f"Quality review complete ({passed}/{total} passed) — preparing final answer…"


def format_defense_trace_preview(reviews: list[DefenseReview]) -> str:
    """Build a short preview of defense check results for AgentTrace."""
    if not reviews:
        return "No segments reviewed."

    passed = sum(1 for review in reviews if review.verdict == "pass")
    revised = [review for review in reviews if review.verdict != "pass"]
    if not revised:
        return f"{passed}/{len(reviews)} segments passed all checks."

    first = revised[0]
    failed_checks = [
        name
        for name, verdict in first.checks.model_dump().items()
        if verdict == "revise"
    ]
    check_hint = ", ".join(failed_checks) if failed_checks else first.verdict
    return f"{passed}/{len(reviews)} passed; {check_hint}: revise"


def build_agents_involved_with_defense(
    state: GraphState,
    *,
    include_combiners: bool,
) -> list[str]:
    """Build the human-readable agent pipeline including defense nodes."""
    pipeline = build_agents_involved(state, include_combiners=include_combiners)
    presenter_name = format_agent_display_name("presenter")
    if presenter_name in pipeline:
        presenter_index = pipeline.index(presenter_name)
        pipeline = [
            *pipeline[:presenter_index],
            *defense_pipeline_names(),
            presenter_name,
        ]
    else:
        pipeline.extend(defense_pipeline_names())
        pipeline.append(presenter_name)
    return pipeline


def build_panel_agents_involved(
    state: GraphState,
    *,
    include_combiners: bool = False,
) -> list[str]:
    """Build agents_involved for Panels, respecting chain_profile depth gates."""
    from app.core.chain_profiles import ChainProfile
    from app.graph.chain_gates import allows_defense

    profile = state.get("chain_profile", ChainProfile.L4.value)
    if profile == ChainProfile.L0.value:
        return [
            "Direct Responder",
            format_agent_display_name("presenter"),
        ]

    if allows_defense(profile):
        return build_agents_involved_with_defense(
            state,
            include_combiners=include_combiners,
        )

    return build_agents_involved(state, include_combiners=include_combiners)


def resolve_retry_specialist(state: GraphState) -> str:
    """Return the specialist agent to re-run on bypass defense retry."""
    from app.agents.registry import AGENT_REGISTRY

    active_agents = state.get("active_agents") or []
    agent = active_agents[0] if active_agents else DEFAULT_AGENT_NAME

    if agent == "general_assistant" and state.get("search_queries"):
        if "researcher" in AGENT_REGISTRY:
            return "researcher"

    if agent in AGENT_REGISTRY:
        return agent
    return DEFAULT_AGENT_NAME
