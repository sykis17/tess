import json
import logging
import re

from app.agents.registry import AGENT_REGISTRY, DEFAULT_AGENT_NAME
from app.agents.schemas import RoutingDecision

logger = logging.getLogger(__name__)

_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def _extract_json_payload(raw: str) -> str:
    """Strip markdown fences and surrounding whitespace from an LLM response."""
    stripped = raw.strip()
    match = _JSON_FENCE_PATTERN.search(stripped)
    if match:
        return match.group(1).strip()
    return stripped


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

    known_agents = [agent for agent in decision.active_agents if agent in AGENT_REGISTRY]
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


def route_after_wr(state: dict) -> str:
    """Route from Wide Receiver to the first supported specialist agent."""
    for agent in state.get("active_agents") or []:
        if agent in AGENT_REGISTRY:
            return agent
    return DEFAULT_AGENT_NAME
