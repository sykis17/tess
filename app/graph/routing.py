import json
import logging
import re

from langgraph.types import Send

from app.agents.registry import AGENT_REGISTRY, DEFAULT_AGENT_NAME
from app.agents.schemas import RoutingDecision
from app.agents.subjects.registry import infer_pov_agents_from_keywords, is_pov_agent
from app.core.product_modes import ProductMode
from app.graph.chain_gates import (
    allows_search,
    max_defense_retries,
    max_routed_agents,
    route_after_fan_in_target,
)

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
        "what are ",
        "how does ",
        "tell me about",
        "summarize ",
        "compare ",
        "research ",
        "happening in",
        "right now",
    )

    if any(signal in text for signal in photo_signals):
        agents.append("photo")
    if any(signal in text for signal in video_signals):
        agents.append("video")
    if any(signal in text for signal in audio_signals):
        agents.append("audio")
    if any(signal in text for signal in coder_signals):
        agents.append("coder")

    pov_agents = infer_pov_agents_from_keywords(text)
    if pov_agents:
        agents.extend(pov_agents)
    elif any(signal in text for signal in research_signals):
        agents.append("researcher")

    return _dedupe_known_agents(agents) or [DEFAULT_AGENT_NAME]


MEDIA_AGENTS = frozenset({"photo", "video", "audio"})
FALLBACK_AGENTS = frozenset({"researcher", DEFAULT_AGENT_NAME})


def _apply_keyword_media_override(
    user_input: str,
    active_agents: list[str],
) -> list[str]:
    """Correct WR misroutes when user input clearly requests a media specialist."""
    keyword_agents = _infer_agents_from_keywords(user_input)
    keyword_media = [agent for agent in keyword_agents if agent in MEDIA_AGENTS]
    if not keyword_media:
        return active_agents

    routed_media = [agent for agent in active_agents if agent in MEDIA_AGENTS]
    if routed_media:
        return active_agents

    if DEFAULT_AGENT_NAME in active_agents and len(active_agents) == 1:
        logger.info(
            "Keyword override: replacing general_assistant with %s for media intent",
            keyword_media,
        )
        return _dedupe_known_agents(keyword_media)

    merged = _dedupe_known_agents([*active_agents, *keyword_media])
    if merged != active_agents:
        logger.info(
            "Keyword override: added media agents %s to routing %s",
            keyword_media,
            active_agents,
        )
    return merged


def _apply_keyword_pov_override(
    user_input: str,
    active_agents: list[str],
) -> list[str]:
    """Correct WR misroutes when user input clearly matches POV keywords."""
    keyword_povs = infer_pov_agents_from_keywords(user_input)
    if not keyword_povs:
        return active_agents

    routed_povs = [agent for agent in active_agents if is_pov_agent(agent)]
    non_pov_agents = [agent for agent in active_agents if not is_pov_agent(agent)]

    keyword_set = set(keyword_povs)
    routed_pov_set = set(routed_povs)

    if not routed_povs and len(active_agents) == 1 and active_agents[0] in FALLBACK_AGENTS:
        logger.info(
            "Keyword override: replacing %s with %s for POV intent",
            active_agents,
            keyword_povs,
        )
        return _dedupe_known_agents(keyword_povs)

    supported_routed = [pov for pov in routed_povs if pov in keyword_set]
    missing_povs = [pov for pov in keyword_povs if pov not in routed_pov_set]
    pruned_povs = [pov for pov in routed_povs if pov not in keyword_set]

    if routed_povs and not supported_routed:
        logger.info(
            "Keyword override: replacing wrong POV %s with %s",
            routed_povs,
            keyword_povs,
        )
        corrected_povs = keyword_povs
    else:
        corrected_povs = [*supported_routed, *missing_povs]
        if pruned_povs:
            logger.info("Keyword override: pruned wrong POVs %s", pruned_povs)
        if missing_povs:
            logger.info(
                "Keyword override: added POV agents %s to routing %s",
                missing_povs,
                active_agents,
            )

    merged = _dedupe_known_agents([*corrected_povs, *non_pov_agents])
    return merged


_CASUAL_GREETING_SIGNALS = (
    "how are you",
    "hello",
    "hi there",
    "hey there",
    "good morning",
    "good evening",
    "hey,",
)


def _looks_like_casual_greeting(user_input: str) -> bool:
    text = user_input.lower().strip()
    return any(signal in text for signal in _CASUAL_GREETING_SIGNALS) and len(text) < 60


def _apply_keyword_researcher_override(
    user_input: str,
    active_agents: list[str],
) -> list[str]:
    """Route broad factual questions away from general_assistant to researcher."""
    if len(active_agents) != 1 or active_agents[0] not in FALLBACK_AGENTS:
        return active_agents
    if active_agents[0] == "researcher":
        return active_agents
    if _looks_like_casual_greeting(user_input):
        return active_agents
    if _looks_like_broad_research_topic(user_input):
        logger.info(
            "Keyword override: replacing %s with researcher for broad research topic",
            active_agents,
        )
        return ["researcher"]
    return active_agents


def apply_auto_routing_nudges(
    decision: RoutingDecision,
    user_input: str,
    chain_profile: str,
) -> RoutingDecision:
    """Apply auto-mode routing corrections and optional search for temporal factual asks."""
    active_agents = _apply_keyword_researcher_override(user_input, list(decision.active_agents))
    search_queries = list(decision.search_queries)
    current_task = decision.current_task

    if active_agents != decision.active_agents and active_agents == ["researcher"]:
        if not current_task or current_task.strip() == user_input.strip():
            current_task = user_input

    temporal_signals = ("right now", "currently", "happening", "latest", "recent", "2024", "2025", "2026")
    text = user_input.lower()
    if (
        allows_search(chain_profile)
        and not search_queries
        and "researcher" in active_agents
        and (
            any(signal in text for signal in temporal_signals)
            or _needs_research_search(user_input)
            or _looks_like_broad_research_topic(user_input)
        )
    ):
        search_queries = [_infer_search_query_from_input(user_input)]
        logger.info("Auto routing: inferred search query for researcher factual ask")

    return RoutingDecision(
        active_agents=active_agents,
        current_task=current_task,
        search_queries=_normalize_search_queries(search_queries),
    )


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


_RESEARCH_SOURCE_SIGNALS = (
    "cite",
    "citation",
    "citations",
    "source",
    "sources",
    "reference",
    "references",
    "latest",
    "recent",
    "current",
    "with sources",
)

_PLAN_LANGUAGE_SIGNALS = (
    "plan",
    "timeline",
    "roadmap",
    "schedule",
    "milestone",
    "checklist",
    "steps",
    "sprint",
)

_CODER_SIGNALS = (
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
    "python ",
    "javascript ",
    "typescript ",
    "function",
    "module",
    "api route",
)

_BUILDER_DELIVERABLE_SIGNALS = (
    "readme",
    "wireframe",
    "html",
    "css",
    "config",
    "documentation",
    "docs",
    "starter",
    "package",
    "landing page",
)

_BROAD_RESEARCH_SIGNALS = (
    "industry",
    "market",
    "sector",
    "company",
    "companies",
    "business",
    "requirements",
    "needs",
    "overview",
    "trends",
    "aviation",
    "aerospace",
    "explain ",
    "what is ",
    "what are ",
    "how does ",
    "tell me about",
    "summarize ",
    "compare ",
    "research ",
    "happening in",
    "right now",
    "currently",
    "latest",
)


def _looks_like_code_request(user_input: str) -> bool:
    text = user_input.lower()
    return any(signal in text for signal in _CODER_SIGNALS)


def _count_builder_deliverables(user_input: str) -> int:
    text = user_input.lower()
    return sum(1 for signal in _BUILDER_DELIVERABLE_SIGNALS if signal in text)


def _needs_research_search(user_input: str) -> bool:
    text = user_input.lower()
    return any(signal in text for signal in _RESEARCH_SOURCE_SIGNALS)


def _infer_search_query_from_input(user_input: str) -> str:
    """Build a simple search query from user input for research mode nudges."""
    text = user_input.strip()
    if len(text) > 120:
        text = text[:120]
    return text


def _looks_like_broad_research_topic(user_input: str) -> bool:
    """Detect industry, business, or general factual questions suited to researcher + search."""
    text = user_input.lower()
    return any(signal in text for signal in _BROAD_RESEARCH_SIGNALS)


def _apply_research_pov_guard(user_input: str, active_agents: list[str]) -> list[str]:
    """Prune POV agents without keyword grounding; fall back to researcher for broad topics."""
    keyword_povs = infer_pov_agents_from_keywords(user_input)
    non_pov_agents = [agent for agent in active_agents if not is_pov_agent(agent)]
    routed_povs = [agent for agent in active_agents if is_pov_agent(agent)]

    if not routed_povs:
        return active_agents

    keyword_set = set(keyword_povs)

    if keyword_povs:
        supported_povs = [pov for pov in routed_povs if pov in keyword_set]
        pruned_povs = [pov for pov in routed_povs if pov not in keyword_set]
        if pruned_povs:
            logger.info("Research guard: pruned unmatched POVs %s", pruned_povs)
        if supported_povs:
            return _dedupe_known_agents([*supported_povs, *non_pov_agents])
        return _dedupe_known_agents([*keyword_povs, *non_pov_agents])

    logger.info(
        "Research guard: no POV keywords in input; replacing %s with researcher",
        routed_povs,
    )
    if non_pov_agents and "researcher" not in non_pov_agents:
        return _dedupe_known_agents([*non_pov_agents, "researcher"])
    if non_pov_agents:
        return _dedupe_known_agents(non_pov_agents)
    return ["researcher"]


def apply_product_mode_routing(
    mode: str,
    decision: RoutingDecision,
    user_input: str,
) -> RoutingDecision:
    """Apply lightweight post-processing nudges after POV/media overrides."""
    if mode == ProductMode.AUTO.value:
        return decision

    active_agents = list(decision.active_agents)
    current_task = decision.current_task
    search_queries = list(decision.search_queries)

    if mode == ProductMode.RESEARCH.value:
        guarded_agents = _apply_research_pov_guard(user_input, active_agents)
        if guarded_agents != active_agents:
            active_agents = guarded_agents
        if not search_queries and (
            _needs_research_search(user_input)
            or "researcher" in active_agents
            or _looks_like_broad_research_topic(user_input)
        ):
            search_queries = [_infer_search_query_from_input(user_input)]
            logger.info("Product mode research: inferred search query from user input")

    elif mode == ProductMode.PLANNER.value:
        task_lower = current_task.lower()
        if not any(signal in task_lower for signal in _PLAN_LANGUAGE_SIGNALS):
            current_task = f"{current_task} — structured plan"
            logger.info("Product mode planner: appended structured plan to current_task")

    elif mode == ProductMode.CODING.value:
        if "coder" not in active_agents and _looks_like_code_request(user_input):
            active_agents = _dedupe_known_agents(["coder"])
            logger.info("Product mode coding: prioritized coder for code-like input")

    elif mode == ProductMode.BUILDER.value:
        deliverable_count = _count_builder_deliverables(user_input)
        if len(active_agents) == 1 and deliverable_count >= 2:
            keyword_agents = _infer_agents_from_keywords(user_input)
            expanded = _dedupe_known_agents([*active_agents, *keyword_agents])
            if len(expanded) > len(active_agents):
                active_agents = expanded
                logger.info(
                    "Product mode builder: expanded agents to %s for multi-deliverable input",
                    active_agents,
                )
        if deliverable_count >= 2 and "deliverable" not in current_task.lower():
            current_task = f"{current_task} — multiple deliverables"

    return RoutingDecision(
        active_agents=active_agents,
        current_task=current_task,
        search_queries=_normalize_search_queries(search_queries),
    )


def _apply_chain_profile_to_decision(
    decision: RoutingDecision,
    chain_profile: str,
) -> RoutingDecision:
    """Trim agents and suppress search per chain profile depth gates."""
    agents = list(decision.active_agents)
    cap = max_routed_agents(chain_profile)
    if len(agents) > cap:
        logger.info(
            "Chain profile %s: trimming active_agents from %s to %s",
            chain_profile,
            agents,
            agents[:cap],
        )
        agents = agents[:cap]

    search_queries = list(decision.search_queries)
    if search_queries and not allows_search(chain_profile):
        logger.info(
            "Chain profile %s: clearing search_queries %s",
            chain_profile,
            search_queries,
        )
        search_queries = []

    return RoutingDecision(
        active_agents=agents,
        current_task=decision.current_task,
        search_queries=search_queries,
    )


def _finalize_routing_decision(
    decision: RoutingDecision,
    fallback_task: str,
    product_mode: str,
    chain_profile: str,
) -> RoutingDecision:
    """Apply auto nudges, product-mode rules, and chain-profile gates."""
    nudged = apply_auto_routing_nudges(decision, fallback_task, chain_profile)
    return _apply_chain_profile_to_decision(
        apply_product_mode_routing(product_mode, nudged, fallback_task),
        chain_profile,
    )


def parse_routing_decision(
    raw: str,
    fallback_task: str,
    product_mode: str = "auto",
    chain_profile: str = "L4",
) -> RoutingDecision:
    """Parse the Wide Receiver routing JSON with a safe fallback."""
    payload = _extract_json_payload(raw)

    try:
        data = json.loads(payload)
        decision = RoutingDecision.model_validate(data)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Failed to parse routing decision; using keyword fallback: %s", exc)
        fallback = RoutingDecision(
            active_agents=_infer_agents_from_keywords(fallback_task),
            current_task=fallback_task,
        )
        return _finalize_routing_decision(fallback, fallback_task, product_mode, chain_profile)

    known_agents = _dedupe_known_agents(decision.active_agents)
    if not known_agents:
        logger.warning("Routing decision had no active agents; using keyword fallback.")
        fallback = RoutingDecision(
            active_agents=_infer_agents_from_keywords(fallback_task),
            current_task=decision.current_task or fallback_task,
            search_queries=_normalize_search_queries(decision.search_queries),
        )
        return _finalize_routing_decision(fallback, fallback_task, product_mode, chain_profile)

    corrected_agents = _apply_keyword_media_override(fallback_task, known_agents)
    corrected_agents = _apply_keyword_pov_override(fallback_task, corrected_agents)

    routed = RoutingDecision(
        active_agents=corrected_agents,
        current_task=decision.current_task or fallback_task,
        search_queries=_normalize_search_queries(decision.search_queries),
    )
    return _finalize_routing_decision(routed, fallback_task, product_mode, chain_profile)


def route_from_start(state: dict) -> str:
    """Route L0 to direct responder; L1–L4 to Wide Receiver."""
    from app.graph.chain_gates import allows_wide_receiver

    profile = state.get("chain_profile", "L4")
    if not allows_wide_receiver(profile):
        return "direct_responder"
    return "wide_receiver"


def fan_out_from_wr(state: dict) -> list[Send]:
    """Fan out from Wide Receiver to specialists and optional search pipeline."""
    agents = state.get("active_agents") or [DEFAULT_AGENT_NAME]
    sends = [Send(agent, state) for agent in agents if agent in AGENT_REGISTRY]

    search_queries = state.get("search_queries") or []
    chain_profile = state.get("chain_profile", "L4")
    if search_queries and allows_search(chain_profile):
        sends.append(Send("resource_finder", state))

    return sends


def fan_out_to_specialists(state: dict) -> list[Send]:
    """Deprecated alias for fan_out_from_wr."""
    return fan_out_from_wr(state)


def route_after_fan_in(state: dict) -> str:
    """Route to combiners, defense, or presenter after parallel branches complete."""
    from app.graph.fan_in_utils import all_fan_in_branches_complete

    if not all_fan_in_branches_complete(state):
        return "fan_in_wait"

    chain_profile = state.get("chain_profile", "L4")
    target = route_after_fan_in_target(chain_profile)
    if target == "presenter":
        return "presenter"
    if target == "defense_delegator":
        return "defense_delegator"

    if state.get("combiners_bypassed"):
        return "defense_delegator"
    return "combiner_mayor"


def route_after_defense(state: dict) -> str:
    """Route to presenter or retry target after defense review."""
    from app.agents.registry import AGENT_REGISTRY, DEFAULT_AGENT_NAME
    from app.graph.defense_utils import (
        all_segments_approved,
        resolve_retry_specialist,
    )

    reviews = state.get("defense_reviews") or []
    retry_count = state.get("defense_retry_count") or 0
    usable_answers = state.get("usable_answers") or []
    chain_profile = state.get("chain_profile", "L4")
    retry_limit = max_defense_retries(chain_profile)

    if not reviews and not usable_answers:
        return "presenter"

    if all_segments_approved(reviews) or retry_count >= retry_limit:
        return "presenter"

    if state.get("combiners_bypassed"):
        agent = resolve_retry_specialist(state)
        if agent in AGENT_REGISTRY:
            return agent
        return DEFAULT_AGENT_NAME

    return "combiner_micro"
