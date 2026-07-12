"""Phase 15B POV routing test matrix."""

from app.agents.registry import AGENT_REGISTRY
from app.agents.subjects.registry import infer_pov_agents_from_keywords, is_pov_agent
from app.graph.routing import _apply_keyword_pov_override, parse_routing_decision


def _route(wr_json: str, user_input: str) -> list[str]:
    return parse_routing_decision(wr_json, user_input).active_agents


def test_ionic_bonding_replaces_wrong_biology_pov() -> None:
    agents = _route(
        '{"active_agents": ["biology"], "current_task": "Explain ionic bonding", "search_queries": []}',
        "Explain ionic bonding",
    )
    assert agents == ["chemistry"]


def test_ionic_bonding_prunes_partial_wrong_pov() -> None:
    agents = _route(
        (
            '{"active_agents": ["biology", "chemistry"], '
            '"current_task": "Explain ionic bonding", "search_queries": []}'
        ),
        "Explain ionic bonding",
    )
    assert agents == ["chemistry"]


def test_ionic_bonding_replaces_researcher_fallback() -> None:
    agents = _route(
        '{"active_agents": ["researcher"], "current_task": "ionic bonding", "search_queries": []}',
        "Explain ionic bonding",
    )
    assert agents == ["chemistry"]


def test_science_app_ui_routes_art_and_ui_design() -> None:
    prompt = "Design a science app UI — cover look and usability"
    povs = infer_pov_agents_from_keywords(prompt)
    assert "art" in povs
    assert "ui_design" in povs

    agents = _route(
        (
            '{"active_agents": ["ui_design"], '
            '"current_task": "Design a science app UI", "search_queries": []}'
        ),
        prompt,
    )
    assert "art" in agents
    assert "ui_design" in agents


def test_renewable_energy_economics_and_chemistry() -> None:
    prompt = "Compare renewable energy economics and chemistry"
    povs = infer_pov_agents_from_keywords(prompt)
    assert "economics" in povs
    assert "chemistry" in povs

    agents = _route(
        (
            '{"active_agents": ["economics", "chemistry"], '
            '"current_task": "Compare renewable energy", "search_queries": []}'
        ),
        prompt,
    )
    assert agents == ["economics", "chemistry"]


def test_supply_and_demand_with_diagram_plan() -> None:
    prompt = "Explain supply and demand and sketch a diagram plan"
    agents = _route(
        (
            '{"active_agents": ["economics"], '
            '"current_task": "Explain supply and demand", "search_queries": []}'
        ),
        prompt,
    )
    assert "economics" in agents
    assert "photo" in agents


def test_kubernetes_routes_to_researcher() -> None:
    agents = _route(
        '{"active_agents": ["researcher"], "current_task": "What is Kubernetes?", "search_queries": []}',
        "What is Kubernetes?",
    )
    assert agents == ["researcher"]


def test_casual_greeting_routes_to_general_assistant() -> None:
    agents = _route("not-json", "Hey, how are you?")
    assert agents == ["general_assistant"]


def test_python_sort_routes_to_coder() -> None:
    agents = _route("not-json", "Write a Python sort function")
    assert agents == ["coder"]


def test_word_boundary_avoids_database_base_false_positive() -> None:
    povs = infer_pov_agents_from_keywords("Explain database indexing")
    assert "chemistry" not in povs


def test_word_boundary_avoids_cellphone_false_positive() -> None:
    povs = infer_pov_agents_from_keywords("Best cellphone plans")
    assert "biology" not in povs


def test_pov_override_prunes_unsupported_routed_povs() -> None:
    corrected = _apply_keyword_pov_override(
        "Explain ionic bonding",
        ["biology", "chemistry", "photo"],
    )
    assert corrected == ["chemistry", "photo"]


def test_pov_registry_has_five_agents() -> None:
    assert is_pov_agent("chemistry")
    assert not is_pov_agent("coder")
    assert len([key for key, config in AGENT_REGISTRY.items() if config.agent_kind == "pov"]) == 5
