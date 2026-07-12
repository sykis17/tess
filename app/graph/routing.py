import json
import logging
import re

from langgraph.types import Send

from app.agents.registry import AGENT_REGISTRY, DEFAULT_AGENT_NAME
from app.agents.schemas import RoutingDecision

logger = logging.getLogger(__name__)

MAX_PARALLEL_AGENTS = 3
MAX_SEARCH_QUERIES = 1

_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def _extract_balanced_json_object(raw: str) -> str | None:
    """Extract the first top-level JSON object from mixed LLM output."""
    start = raw.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False

    for index in range(start, len(raw)):
        char = raw[index]
        if escape:
            escape = False
            continue
        if char == "\\" and in_string:
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return raw[start : index + 1]
    return None


def _extract_json_payload(raw: str) -> str:
    """Strip markdown fences and surrounding whitespace from an LLM response."""
    stripped = raw.strip()
    match = _JSON_FENCE_PATTERN.search(stripped)
    if match:
        return match.group(1).strip()
    balanced = _extract_balanced_json_object(stripped)
    if balanced:
        return balanced
    return stripped


def _infer_agents_from_keywords(user_input: str) -> list[str]:
    """Heuristic agent routing when WR JSON parsing fails (small-model fallback)."""
    text = user_input.lower().strip()
    agents: list[str] = []

    greeting_signals = ("how are you", "hello", "hi there", "hey there", "good morning", "good evening")
    if any(signal in text for signal in greeting_signals) and len(text) < 50:
        return [DEFAULT_AGENT_NAME]

    photo_signals = (
        "diagram plan",
        "diagram for",
        "sketch a",
        "sketch ",
        "draw a diagram",
        "draw a diagram plan",
        "draw a plan",
        "image plan",
        "visual layout",
        "illustration plan",
        "icon design",
    )
    video_signals = (
        "video script",
        "storyboard",
        "shot list",
        "edit plan",
        "-second video",
        "second video",
    )
    audio_signals = (
        "podcast intro",
        "podcast outline",
        "podcast episode",
        "voiceover",
        "narration script",
        "audio outline",
    )
    coder_signals = (
        "write a python",
        "write python",
        "debug ",
        "refactor ",
        "fastapi",
        "hello-world",
        "hello world",
        "sort function",
        "cli tool",
        "build a ",
        "code ",
    )
    research_signals = (
        "explain ",
        "what is ",
        "how does ",
        "tell me about",
        "summarize ",
        "compare ",
        "research ",
    )

    if any(signal in text for signal in photo_signals):
        agents.append("photo")
    if any(signal in text for signal in video_signals):
        agents.append("video")
    if any(signal in text for signal in audio_signals):
        agents.append("audio")
    if any(signal in text for signal in coder_signals):
        agents.append("coder")
    if any(signal in text for signal in research_signals):
        agents.append("researcher")

    return _dedupe_known_agents(agents) or [DEFAULT_AGENT_NAME]


def _dedupe_known_agents(agents: list[str]) -> list[str]:
    """Filter to registered agents, dedupe, and cap at MAX_PARALLEL_AGENTS."""
    seen: set[str] = set()
    known: list[str] = []
    for agent in agents:
        if agent in AGENT_REGISTRY and agent not in seen:
            seen.add(agent)
            known.append(agent)
        if len(known) >= MAX_PARALLEL_AGENTS:
            break
    return known


def _normalize_search_queries(queries: list[str]) -> list[str]:
    """Strip empty queries and cap at MAX_SEARCH_QUERIES."""
    cleaned = [q.strip() for q in queries if q and q.strip()]
    return cleaned[:MAX_SEARCH_QUERIES]


def parse_routing_decision(raw: str, fallback_task: str) -> RoutingDecision:
    """Parse the Wide Receiver routing JSON with a safe fallback."""
    payload = _extract_json_payload(raw)

    try:
        data = json.loads(payload)
        decision = RoutingDecision.model_validate(data)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Failed to parse routing decision; using keyword fallback: %s", exc)
        return RoutingDecision(
            active_agents=_infer_agents_from_keywords(fallback_task),
            current_task=fallback_task,
        )

    known_agents = _dedupe_known_agents(decision.active_agents)
    if not known_agents:
        logger.warning("Routing decision had no active agents; using keyword fallback.")
        return RoutingDecision(
            active_agents=_infer_agents_from_keywords(fallback_task),
            current_task=decision.current_task or fallback_task,
            search_queries=_normalize_search_queries(decision.search_queries),
        )

    return RoutingDecision(
        active_agents=known_agents,
        current_task=decision.current_task or fallback_task,
        search_queries=_normalize_search_queries(decision.search_queries),
    )


def fan_out_from_wr(state: dict) -> list[Send]:
    """Fan out from Wide Receiver to specialists and optional search pipeline."""
    agents = state.get("active_agents") or [DEFAULT_AGENT_NAME]
    sends = [Send(agent, state) for agent in agents if agent in AGENT_REGISTRY]

    search_queries = state.get("search_queries") or []
    if search_queries:
        sends.append(Send("resource_finder", state))

    return sends


def fan_out_to_specialists(state: dict) -> list[Send]:
    """Deprecated alias for fan_out_from_wr."""
    return fan_out_from_wr(state)


def route_after_fan_in(state: dict) -> str:
    """Route to combiners or defense after all parallel branches complete."""
    from app.graph.fan_in_utils import all_fan_in_branches_complete

    if not all_fan_in_branches_complete(state):
        return "fan_in_wait"

    if state.get("combiners_bypassed"):
        return "defense_delegator"
    return "combiner_mayor"


def route_after_defense(state: dict) -> str:
    """Route to presenter or retry target after defense review."""
    from app.agents.registry import AGENT_REGISTRY, DEFAULT_AGENT_NAME
    from app.graph.defense_utils import (
        MAX_DEFENSE_RETRIES,
        all_segments_approved,
        resolve_retry_specialist,
    )

    reviews = state.get("defense_reviews") or []
    retry_count = state.get("defense_retry_count") or 0
    usable_answers = state.get("usable_answers") or []

    if not reviews and not usable_answers:
        return "presenter"

    if all_segments_approved(reviews) or retry_count >= MAX_DEFENSE_RETRIES:
        return "presenter"

    if state.get("combiners_bypassed"):
        agent = resolve_retry_specialist(state)
        if agent in AGENT_REGISTRY:
            return agent
        return DEFAULT_AGENT_NAME

    return "combiner_micro"
