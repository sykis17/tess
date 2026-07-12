"""Phase 16 product mode tests — payload parsing and routing nudges."""

import json

from app.agents.schemas import RoutingDecision
from app.core.ws_payload import parse_incoming_payload
from app.graph.routing import apply_product_mode_routing, parse_routing_decision


# --- Payload parsing ---


def test_plain_text_payload_maps_to_auto() -> None:
    text, mode = parse_incoming_payload("Hey, how are you?")
    assert text == "Hey, how are you?"
    assert mode == "auto"


def test_valid_json_envelope_parses_text_and_mode() -> None:
    payload = json.dumps(
        {"text": "Explain photosynthesis with citations", "product_mode": "research"}
    )
    text, mode = parse_incoming_payload(payload)
    assert text == "Explain photosynthesis with citations"
    assert mode == "research"


def test_invalid_json_falls_back_to_plain_text() -> None:
    raw = "not json at all"
    text, mode = parse_incoming_payload(raw)
    assert text == raw
    assert mode == "auto"


def test_invalid_product_mode_maps_to_auto() -> None:
    payload = json.dumps({"text": "Hello", "product_mode": "invalid_mode"})
    text, mode = parse_incoming_payload(payload)
    assert text == "Hello"
    assert mode == "auto"


def test_json_without_text_falls_back_to_plain_text() -> None:
    payload = json.dumps({"product_mode": "research"})
    text, mode = parse_incoming_payload(payload)
    assert text == payload
    assert mode == "auto"


# --- Routing nudges ---


def _route(wr_json: str, user_input: str, product_mode: str = "auto") -> RoutingDecision:
    return parse_routing_decision(wr_json, user_input, product_mode=product_mode)


def test_research_mode_nudges_search_queries() -> None:
    decision = _route(
        '{"active_agents": ["biology"], "current_task": "Explain photosynthesis", "search_queries": []}',
        "Explain photosynthesis with citations",
        product_mode="research",
    )
    assert "biology" in decision.active_agents
    assert len(decision.search_queries) == 1


def test_planner_mode_appends_plan_language() -> None:
    decision = _route(
        '{"active_agents": ["ui_design"], "current_task": "UI design work", "search_queries": []}',
        "Plan a 2-week UI design sprint",
        product_mode="planner",
    )
    assert "ui_design" in decision.active_agents
    assert "plan" in decision.current_task.lower()


def test_coding_mode_prioritizes_coder() -> None:
    decision = _route(
        '{"active_agents": ["general_assistant"], "current_task": "Sort function", "search_queries": []}',
        "Write a Python sort function",
        product_mode="coding",
    )
    assert decision.active_agents == ["coder"]


def test_builder_mode_expands_multi_deliverable_input() -> None:
    decision = _route(
        '{"active_agents": ["coder"], "current_task": "Science app package", "search_queries": []}',
        "README + wireframe + HTML for science app",
        product_mode="builder",
    )
    assert len(decision.active_agents) >= 2


def test_auto_mode_does_not_apply_nudges() -> None:
    decision = _route(
        '{"active_agents": ["general_assistant"], "current_task": "Casual greeting", "search_queries": []}',
        "Hey, how are you?",
        product_mode="auto",
    )
    assert decision.active_agents == ["general_assistant"]
    assert decision.search_queries == []


def test_auto_mode_preserves_pov_override() -> None:
    """Phase 15B POV override must not regress under auto mode."""
    decision = _route(
        '{"active_agents": ["biology"], "current_task": "Explain ionic bonding", "search_queries": []}',
        "Explain ionic bonding",
        product_mode="auto",
    )
    assert decision.active_agents == ["chemistry"]


def test_apply_product_mode_routing_research_direct() -> None:
    decision = RoutingDecision(
        active_agents=["biology"],
        current_task="Explain topic",
        search_queries=[],
    )
    result = apply_product_mode_routing(
        "research",
        decision,
        "Compare sources and cite references",
    )
    assert len(result.search_queries) == 1


def test_apply_product_mode_routing_auto_noop() -> None:
    decision = RoutingDecision(
        active_agents=["general_assistant"],
        current_task="Hello",
        search_queries=[],
    )
    result = apply_product_mode_routing("auto", decision, "Hey, how are you?")
    assert result == decision


def test_research_guard_prunes_unmatched_povs_for_aviation_industry() -> None:
    """WR over-alarm of POVs without keyword grounding should fall back to researcher + search."""
    decision = _route(
        (
            '{"active_agents": ["economics", "biology", "chemistry"], '
            '"current_task": "Aviation industry needs and company requirements", "search_queries": []}'
        ),
        "Aviation industry needs and company requirements",
        product_mode="research",
    )
    assert decision.active_agents == ["researcher"]
    assert len(decision.search_queries) == 1


def test_research_guard_keeps_keyword_matched_multi_pov() -> None:
    decision = _route(
        (
            '{"active_agents": ["economics", "chemistry", "biology"], '
            '"current_task": "Compare renewable energy economics and chemistry", "search_queries": []}'
        ),
        "Compare renewable energy economics and chemistry",
        product_mode="research",
    )
    assert "economics" in decision.active_agents
    assert "chemistry" in decision.active_agents
    assert "biology" not in decision.active_agents


def test_research_guard_keeps_biology_for_photosynthesis() -> None:
    decision = _route(
        '{"active_agents": ["biology"], "current_task": "Explain photosynthesis", "search_queries": []}',
        "Explain photosynthesis",
        product_mode="research",
    )
    assert decision.active_agents == ["biology"]
    assert len(decision.search_queries) == 1


def test_auto_mode_does_not_apply_research_guard() -> None:
    decision = _route(
        (
            '{"active_agents": ["economics", "biology", "chemistry"], '
            '"current_task": "Aviation industry needs", "search_queries": []}'
        ),
        "Aviation industry needs and company requirements",
        product_mode="auto",
    )
    assert decision.active_agents == ["economics", "biology", "chemistry"]
    assert decision.search_queries == []
