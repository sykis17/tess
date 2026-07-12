"""Quick Phase 15B routing smoke tests."""
from app.agents.registry import AGENT_REGISTRY
from app.agents.subjects.registry import infer_pov_agents_from_keywords, is_pov_agent
from app.graph.routing import parse_routing_decision

# Wrong POV -> chemistry for ionic bonding
decision = parse_routing_decision(
    '{"active_agents": ["biology"], "current_task": "Explain ionic bonding", "search_queries": []}',
    "Explain ionic bonding",
)
assert decision.active_agents == ["chemistry"], decision.active_agents

# Researcher fallback -> chemistry
decision2 = parse_routing_decision(
    '{"active_agents": ["researcher"], "current_task": "ionic bonding", "search_queries": []}',
    "Explain ionic bonding",
)
assert "chemistry" in decision2.active_agents

# Multi-POV keywords
povs = infer_pov_agents_from_keywords("design a science app ui cover look and usability")
assert "art" in povs or "ui_design" in povs

assert is_pov_agent("chemistry")
assert not is_pov_agent("coder")
assert len([k for k, v in AGENT_REGISTRY.items() if v.agent_kind == "pov"]) == 5

print("All Phase 15B smoke tests passed")
