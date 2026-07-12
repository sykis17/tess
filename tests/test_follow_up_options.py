"""Phase 19 follow-up suggestion generator tests."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.graph.follow_up_utils import (
    build_fallback_follow_ups,
    generate_follow_up_options,
    parse_follow_up_json,
)
from app.graph.nodes.presenter import presenter_node
from app.graph.schemas import DEFAULT_FOLLOW_UP_OPTIONS, MayorData, PanelSegment, UsableAnswer
from app.graph.state import build_initial_state
from app.llm.types import LLMResponse


def _mock_llm_response(content: str) -> LLMResponse:
    return LLMResponse(content=content, provider="test", model="test-model")


def _sample_follow_up_json() -> str:
    return json.dumps(
        {
            "suggestions": [
                {"label": "Who is the target audience?", "kind": "related", "prompt": None},
                {"label": "Clarify scope for mobile", "kind": "related", "prompt": None},
                {"label": "Compare to gaming app UI", "kind": "deviating", "prompt": None},
                {"label": "Sketch wireframes next", "kind": "choice", "prompt": None},
            ]
        }
    )


def test_parse_follow_up_json_happy_path() -> None:
    suggestions = parse_follow_up_json(_sample_follow_up_json())
    assert len(suggestions) == 4
    assert suggestions[0].label == "Who is the target audience?"
    assert suggestions[2].kind == "deviating"


def test_parse_follow_up_json_array_form() -> None:
    raw = json.dumps(
        [{"label": "Go deeper on accessibility", "kind": "choice", "prompt": None}]
    )
    suggestions = parse_follow_up_json(raw)
    assert len(suggestions) == 1
    assert suggestions[0].kind == "choice"


def test_parse_follow_up_json_malformed_raises() -> None:
    with pytest.raises((ValueError, json.JSONDecodeError)):
        parse_follow_up_json("not json")


def test_build_fallback_follow_ups_with_segment_drill_down() -> None:
    segments = [
        PanelSegment(title="Usability patterns", content="Nav and touch targets."),
    ]
    labels, kinds = build_fallback_follow_ups(segments, "## Overview\n\nBody")
    assert labels[0] == "Tell me more about Usability patterns"
    assert kinds[0] == "drill_down"
    assert len(labels) == 4


def test_build_fallback_follow_ups_from_heading() -> None:
    labels, kinds = build_fallback_follow_ups([], "## Color palette\n\nBlue tones.")
    assert labels[0] == "Tell me more about Color palette"
    assert kinds[0] == "drill_down"


def test_build_fallback_follow_ups_skips_agent_heading() -> None:
    content = (
        "## Researcher\n\n"
        "### Electric and Hybrid-Electric Propulsion\n\nDetails.\n\n"
        "### Artificial Intelligence (AI) in Aviation\n\nMore details."
    )
    labels, kinds = build_fallback_follow_ups([], content, ["researcher"])
    assert "Tell me more about Researcher" not in labels
    assert labels[0].startswith("Tell me more about Electric")
    assert kinds[0] == "drill_down"


@patch("app.graph.follow_up_utils.create_llm")
def test_generate_follow_up_options_returns_non_default(mock_create_llm) -> None:
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = _mock_llm_response(_sample_follow_up_json())
    mock_create_llm.return_value = mock_llm

    labels, kinds = asyncio.run(
        generate_follow_up_options(
            content="UI design answer about usability.",
            pov_segments=[],
            product_mode="research",
            active_agents=["ui_design"],
            user_input="Design a science app UI",
        )
    )

    assert labels != list(DEFAULT_FOLLOW_UP_OPTIONS)
    assert "Compare to gaming app UI" in labels
    assert "deviating" in kinds


@patch("app.graph.follow_up_utils.create_llm")
def test_generate_follow_up_options_fallback_on_error(mock_create_llm) -> None:
    mock_llm = AsyncMock()
    mock_llm.generate.side_effect = RuntimeError("LLM unavailable")
    mock_create_llm.return_value = mock_llm

    labels, kinds = asyncio.run(
        generate_follow_up_options(
            content="Answer body",
            pov_segments=[],
            product_mode=None,
            active_agents=["coder"],
            user_input="Write code",
        )
    )

    assert labels[:3] == DEFAULT_FOLLOW_UP_OPTIONS
    assert kinds[:3] == ["choice", "choice", "choice"]


@patch("app.graph.follow_up_utils.create_llm")
def test_presenter_emits_generated_follow_ups(mock_create_llm) -> None:
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = _mock_llm_response(_sample_follow_up_json())
    mock_create_llm.return_value = mock_llm

    state = build_initial_state("Design a science app UI", panel_id="fu-panel")
    state["active_agents"] = ["art", "ui_design"]
    state["combiners_bypassed"] = False
    state["usable_answers"] = [
        UsableAnswer(
            segment_id="seg-1",
            order_hint=1,
            title="Aesthetics",
            content="Warm colors.",
            review_status="approved",
            source_agents=["art"],
        ),
    ]

    result = asyncio.run(presenter_node(state))
    panel = result["panels"][0]

    assert panel.follow_up_options != list(DEFAULT_FOLLOW_UP_OPTIONS)
    assert len(panel.follow_up_kinds) == len(panel.follow_up_options)


@patch("app.graph.follow_up_utils.create_llm")
def test_presenter_fallback_follow_ups_on_llm_error(mock_create_llm) -> None:
    mock_llm = AsyncMock()
    mock_llm.generate.side_effect = RuntimeError("timeout")
    mock_create_llm.return_value = mock_llm

    state = build_initial_state("Hello", panel_id="fallback-panel")
    state["collected_data"] = ["Hi there."]
    state["mayor_data"] = [
        MayorData(source_agent="general_assistant", content="Hi there."),
    ]
    state["active_agents"] = ["general_assistant"]

    result = asyncio.run(presenter_node(state))
    panel = result["panels"][0]

    assert panel.follow_up_options[:3] == DEFAULT_FOLLOW_UP_OPTIONS
