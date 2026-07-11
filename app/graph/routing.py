import json
import logging
import re

from langgraph.types import Send

from app.agents.registry import AGENT_REGISTRY, DEFAULT_AGENT_NAME
from app.agents.schemas import RoutingDecision

logger = logging.getLogger(__name__)

MAX_PARALLEL_AGENTS = 3

_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def _extract_json_payload(raw: str) -> str:
    """Strip markdown fences and surrounding whitespace from an LLM response."""
    stripped = raw.strip()
    match = _JSON_FENCE_PATTERN.search(stripped)
    if match:
        return match.group(1).strip()
    return stripped


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


def parse_routing_decision(raw: str, fallback_task: str) -> RoutingDecision:
    """Parse the Wide Receiver routing JSON with a safe fallback."""
    payload = _extract_json_payload(raw)

    try:
        data = json.loads(payload)
        decision = RoutingDecision.model_validate(data)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Failed to parse routing decision; using fallback: %s", exc)
        return RoutingDecision(
            active_agents=[DEFAULT_AGENT_NAME],
            current_task=fallback_task,
        )

    known_agents = _dedupe_known_agents(decision.active_agents)
    if not known_agents:
        logger.warning("Routing decision had no active agents; using fallback.")
        return RoutingDecision(
            active_agents=[DEFAULT_AGENT_NAME],
            current_task=decision.current_task or fallback_task,
        )

    return RoutingDecision(
        active_agents=known_agents,
        current_task=decision.current_task or fallback_task,
    )


def fan_out_to_specialists(state: dict) -> list[Send]:
    """Fan out from Wide Receiver to all alarmed specialist agents in parallel."""
    agents = state.get("active_agents") or [DEFAULT_AGENT_NAME]
    return [Send(agent, state) for agent in agents if agent in AGENT_REGISTRY]
