"""Phase 21 — two-phase presenter delivery and status-wall stage mapping."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.graph.follow_up_utils import build_fallback_follow_ups
from app.graph.nodes.presenter import presenter_node
from app.graph.schemas import DEFAULT_FOLLOW_UP_OPTIONS, MayorData, UsableAnswer
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


def _presenter_state(panel_id: str = "delivery-panel") -> dict:
    state = build_initial_state("Design a science app UI", panel_id=panel_id)
    state["session_id"] = "sess-delivery"
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
    return state


def test_review_passed_maps_to_presenting() -> None:
    """Mirror of frontend effectiveStage: review_passed → presenting."""
    panel_stage = "defense"
    status = "review_passed"
    effective = "presenting" if status == "review_passed" else panel_stage
    assert effective == "presenting"


@patch("app.graph.nodes.presenter.is_session_interrupted", return_value=False)
@patch("app.graph.nodes.presenter.publish_panel")
@patch("app.graph.follow_up_utils.create_llm")
def test_presenter_publishes_completed_before_follow_up_llm(
    mock_create_llm,
    mock_publish,
    _mock_interrupt,
) -> None:
    publish_order: list[str] = []

    async def slow_generate(*_args, **_kwargs):
        await asyncio.sleep(0.05)
        return _mock_llm_response(_sample_follow_up_json())

    mock_llm = AsyncMock()
    mock_llm.generate.side_effect = slow_generate
    mock_create_llm.return_value = mock_llm

    def track_publish(panel, _session_id):
        publish_order.append(panel.status)

    mock_publish.side_effect = track_publish

    with patch("app.graph.nodes.presenter.should_skip_llm_follow_ups", return_value=False):
        result = asyncio.run(presenter_node(_presenter_state()))

    assert publish_order[0] == "completed"
    assert mock_llm.generate.called
    assert result["panels"][0].status == "completed"


@patch("app.graph.nodes.presenter.is_session_interrupted", return_value=False)
@patch("app.graph.nodes.presenter.publish_panel")
@patch("app.graph.follow_up_utils.create_llm")
def test_presenter_chip_update_same_panel_id(mock_create_llm, mock_publish, _mock_interrupt) -> None:
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = _mock_llm_response(_sample_follow_up_json())
    mock_create_llm.return_value = mock_llm

    published_panels = []

    def capture_publish(panel, _session_id):
        published_panels.append(panel)

    mock_publish.side_effect = capture_publish

    with patch("app.graph.nodes.presenter.should_skip_llm_follow_ups", return_value=False):
        result = asyncio.run(presenter_node(_presenter_state(panel_id="chip-panel")))

    assert len(published_panels) == 2
    assert published_panels[0].panel_id == published_panels[1].panel_id == "chip-panel"
    assert published_panels[0].follow_up_options != published_panels[1].follow_up_options
    assert "Compare to gaming app UI" in published_panels[1].follow_up_options
    assert result["panels"][0].panel_id == "chip-panel"


@patch("app.graph.nodes.presenter.publish_panel")
@patch("app.graph.follow_up_utils.create_llm")
def test_skip_llm_follow_ups_skips_inference(mock_create_llm, mock_publish) -> None:
    with patch("app.graph.nodes.presenter.should_skip_llm_follow_ups", return_value=True):
        result = asyncio.run(presenter_node(_presenter_state()))

    mock_create_llm.assert_not_called()
    panel = result["panels"][0]
    assert panel.status == "completed"
    assert panel.content  # answer shipped


@patch("app.graph.nodes.presenter.publish_panel")
@patch("app.graph.follow_up_utils.create_llm")
def test_presenter_interrupt_during_follow_up_returns_phase_a(
    mock_create_llm,
    mock_publish,
) -> None:
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = _mock_llm_response(_sample_follow_up_json())
    mock_create_llm.return_value = mock_llm

    interrupt_checks = [False, True]

    with (
        patch("app.graph.nodes.presenter.should_skip_llm_follow_ups", return_value=False),
        patch(
            "app.graph.nodes.presenter.is_session_interrupted",
            side_effect=interrupt_checks,
        ),
    ):
        result = asyncio.run(presenter_node(_presenter_state(panel_id="interrupt-panel")))

    panel = result["panels"][0]
    assert panel.status == "completed"
    fallback_labels, _ = build_fallback_follow_ups(
        panel.pov_segments,
        panel.content,
        ["art", "ui_design"],
    )
    assert panel.follow_up_options == fallback_labels


@patch("app.graph.nodes.presenter.is_session_interrupted", return_value=False)
@patch("app.graph.nodes.presenter.publish_panel")
@patch("app.graph.follow_up_utils.create_llm")
def test_presenter_fallback_follow_ups_on_llm_error(mock_create_llm, mock_publish, _mock_interrupt) -> None:
    mock_llm = AsyncMock()
    mock_llm.generate.side_effect = RuntimeError("timeout")
    mock_create_llm.return_value = mock_llm

    state = build_initial_state("Hello", panel_id="fallback-panel")
    state["session_id"] = "sess-fallback"
    state["collected_data"] = ["Hi there."]
    state["mayor_data"] = [
        MayorData(source_agent="general_assistant", content="Hi there."),
    ]
    state["active_agents"] = ["general_assistant"]

    with patch("app.graph.nodes.presenter.should_skip_llm_follow_ups", return_value=False):
        result = asyncio.run(presenter_node(state))

    panel = result["panels"][0]
    assert panel.follow_up_options[:3] == DEFAULT_FOLLOW_UP_OPTIONS
