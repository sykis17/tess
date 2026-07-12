"""Phase 17 chain profile tests — registry, gates, payload, routing."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

from app.core.chain_profiles import (
    default_for_product_mode,
    resolve_chain_profile,
    validate_chain_profile,
)
from app.core.ws_payload import parse_incoming_payload
from app.graph.chain_gates import (
    allows_combiners,
    allows_defense,
    allows_search,
    allows_wide_receiver,
    max_defense_retries,
    max_routed_agents,
    route_after_fan_in_target,
)
from app.graph.defense_utils import build_panel_agents_involved
from app.graph.nodes.presenter import presenter_node
from app.graph.routing import parse_routing_decision, route_from_start
from app.graph.schemas import MayorData
from app.graph.state import build_initial_state
from app.llm.types import LLMResponse


def _run_presenter(state):
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = LLMResponse(
        content='{"suggestions": [{"label": "Go deeper", "kind": "choice", "prompt": null}]}',
        provider="test",
        model="test-model",
    )
    with (
        patch("app.graph.follow_up_utils.create_llm", return_value=mock_llm),
        patch("app.graph.nodes.presenter.publish_panel"),
        patch("app.graph.nodes.presenter.should_skip_llm_follow_ups", return_value=False),
        patch("app.graph.nodes.presenter.is_session_interrupted", return_value=False),
    ):
        return asyncio.run(presenter_node(state))


# --- Registry ---


def test_validate_chain_profile_accepts_valid_keys() -> None:
    assert validate_chain_profile("L0") == "L0"
    assert validate_chain_profile("L1+") == "L1+"
    assert validate_chain_profile("L4") == "L4"


def test_validate_chain_profile_unknown_maps_to_l4() -> None:
    assert validate_chain_profile("L99") == "L4"
    assert validate_chain_profile(None) == "L4"


def test_default_for_product_mode() -> None:
    assert default_for_product_mode("research") == "L3"
    assert default_for_product_mode("planner") == "L2"
    assert default_for_product_mode("coding") == "L1"
    assert default_for_product_mode("builder") == "L4"
    assert default_for_product_mode("auto") == "L4"


def test_resolve_chain_profile_plain_text_always_l4() -> None:
    assert resolve_chain_profile(None, "research", is_plain_text=True) == "L4"


def test_resolve_chain_profile_json_uses_mode_default() -> None:
    assert resolve_chain_profile(None, "research", is_plain_text=False) == "L3"
    assert resolve_chain_profile(None, "coding", is_plain_text=False) == "L1"


def test_resolve_chain_profile_explicit_overrides_mode() -> None:
    assert resolve_chain_profile("L0", "research", is_plain_text=False) == "L0"


# --- WS payload ---


def test_json_explicit_chain_profile() -> None:
    payload = json.dumps({"text": "Hello", "chain_profile": "L0"})
    text, mode, profile = parse_incoming_payload(payload)
    assert text == "Hello"
    assert mode == "auto"
    assert profile == "L0"


def test_json_invalid_chain_profile_falls_back_to_l4() -> None:
    payload = json.dumps({"text": "Hello", "chain_profile": "invalid"})
    _, _, profile = parse_incoming_payload(payload)
    assert profile == "L4"


# --- Chain gates ---


def test_allows_wide_receiver() -> None:
    assert allows_wide_receiver("L0") is False
    assert allows_wide_receiver("L1") is True
    assert allows_wide_receiver("L4") is True


def test_allows_search() -> None:
    assert allows_search("L2") is False
    assert allows_search("L3") is True
    assert allows_search("L4") is True


def test_allows_combiners() -> None:
    assert allows_combiners("L3") is False
    assert allows_combiners("L4") is True


def test_allows_defense() -> None:
    assert allows_defense("L1") is False
    assert allows_defense("L1+") is False
    assert allows_defense("L2") is True
    assert allows_defense("L4") is True


def test_max_routed_agents() -> None:
    assert max_routed_agents("L1") == 1
    assert max_routed_agents("L2") == 1
    assert max_routed_agents("L1+") == 3
    assert max_routed_agents("L4") == 3


def test_route_after_fan_in_target() -> None:
    assert route_after_fan_in_target("L1") == "presenter"
    assert route_after_fan_in_target("L1+") == "presenter"
    assert route_after_fan_in_target("L2") == "defense_delegator"
    assert route_after_fan_in_target("L3") == "defense_delegator"
    assert route_after_fan_in_target("L4") == "defer"


def test_max_defense_retries() -> None:
    assert max_defense_retries("L4") == 2
    assert max_defense_retries("L2") == 1


# --- Routing integration ---


def test_parse_routing_decision_l1_trims_agents() -> None:
    decision = parse_routing_decision(
        '{"active_agents": ["art", "ui_design", "coder"], "current_task": "UI work", "search_queries": []}',
        "Design UI",
        chain_profile="L1",
    )
    assert decision.active_agents == ["art"]


def test_parse_routing_decision_l1_clears_search() -> None:
    decision = parse_routing_decision(
        '{"active_agents": ["researcher"], "current_task": "Research", "search_queries": ["test query"]}',
        "Explain X with citations",
        product_mode="research",
        chain_profile="L1",
    )
    assert decision.search_queries == []


def test_parse_routing_decision_l3_keeps_search() -> None:
    decision = parse_routing_decision(
        '{"active_agents": ["researcher"], "current_task": "Research", "search_queries": ["test query"]}',
        "Explain X with citations",
        product_mode="research",
        chain_profile="L3",
    )
    assert len(decision.search_queries) == 1


def test_parse_routing_decision_l1_plus_allows_multi_agent() -> None:
    decision = parse_routing_decision(
        '{"active_agents": ["art", "ui_design"], "current_task": "UI design", "search_queries": []}',
        "Design a science app UI covering aesthetics and usability",
        chain_profile="L1+",
    )
    assert decision.active_agents == ["art", "ui_design"]


def test_route_from_start_l0() -> None:
    assert route_from_start({"chain_profile": "L0"}) == "direct_responder"


def test_route_from_start_l4() -> None:
    assert route_from_start({"chain_profile": "L4"}) == "wide_receiver"


def test_build_panel_agents_involved_l0() -> None:
    state = build_initial_state("Hello", chain_profile="L0")
    pipeline = build_panel_agents_involved(state)
    assert pipeline == ["Direct Responder", "Presenter"]
    assert "Wide Receiver" not in pipeline
    assert "Defense" not in " ".join(pipeline)


def test_build_panel_agents_involved_l1_skips_defense() -> None:
    state = build_initial_state("Write code", chain_profile="L1")
    state["active_agents"] = ["coder"]
    pipeline = build_panel_agents_involved(state)
    assert pipeline[0] == "Wide Receiver"
    assert "Coder" in pipeline
    assert "Defense Delegator" not in pipeline
    assert pipeline[-1] == "Presenter"


def test_l0_presenter_completed_panel_pipeline() -> None:
    state = build_initial_state(
        "Aviation industry needs",
        panel_id="test-panel",
        chain_profile="L0",
    )
    state["collected_data"] = ["Direct answer about aviation."]
    state["mayor_data"] = [
        MayorData(
            source_agent="direct_responder",
            content="Direct answer about aviation.",
        )
    ]

    result = _run_presenter(state)
    panel = result["panels"][0]

    assert panel.output_level == "L0"
    assert panel.agents_involved == ["Direct Responder", "Presenter"]
    assert panel.status == "completed"
    assert "wide_receiver" not in {trace.agent_name for trace in panel.agent_traces}
