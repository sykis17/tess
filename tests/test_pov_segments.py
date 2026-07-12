"""Phase 18 POV segment builder tests."""

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

from app.graph.nodes.presenter import presenter_node
from app.graph.pipeline_stages import PipelineStage
from app.graph.pov_segments import build_pov_segments
from app.graph.schemas import MayorData, UsableAnswer
from app.graph.state import build_initial_state


from app.llm.types import LLMResponse


def _run_presenter(state):
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = LLMResponse(
        content='{"suggestions": [{"label": "Go deeper", "kind": "choice", "prompt": null}]}',
        provider="test",
        model="test-model",
    )
    with patch("app.graph.follow_up_utils.create_llm", return_value=mock_llm):
        return asyncio.run(presenter_node(state))


def test_build_pov_segments_multi_usable_answers() -> None:
    answers = [
        UsableAnswer(
            segment_id=str(uuid.uuid4()),
            order_hint=1,
            title="Visual composition",
            content="Blue palette and open layout.",
            source_agents=["art"],
        ),
        UsableAnswer(
            segment_id=str(uuid.uuid4()),
            order_hint=2,
            title="Usability patterns",
            content="Clear navigation and touch targets.",
            source_agents=["ui_design"],
        ),
    ]
    segments = build_pov_segments(answers, [], ["art", "ui_design"], False, False)
    assert len(segments) == 2
    povs = {s.pov for s in segments}
    assert "Art" in povs
    assert "UI Design" in povs


def test_build_pov_segments_single_agent_empty() -> None:
    answers = [
        UsableAnswer(
            segment_id=str(uuid.uuid4()),
            order_hint=1,
            title="Overview",
            content="Single answer.",
            source_agents=["coder"],
        ),
    ]
    segments = build_pov_segments(answers, [], ["coder"], False, False)
    assert segments == []


def test_build_pov_segments_single_researcher_multiple_themes_empty() -> None:
    """Single researcher with thematic usable_answers must not emit POV blocks."""
    answers = [
        UsableAnswer(
            segment_id=str(uuid.uuid4()),
            order_hint=1,
            title="Researcher",
            content="Cybersecurity threat landscape overview.",
            source_agents=["researcher"],
        ),
        UsableAnswer(
            segment_id=str(uuid.uuid4()),
            order_hint=2,
            title="Researcher",
            content="Zero-trust architecture patterns.",
            source_agents=["researcher"],
        ),
        UsableAnswer(
            segment_id=str(uuid.uuid4()),
            order_hint=3,
            title="Researcher",
            content="Incident response best practices.",
            source_agents=["researcher"],
        ),
    ]
    segments = build_pov_segments(answers, [], ["researcher"], True, False)
    assert segments == []


def test_build_pov_segments_single_mayor_data_empty() -> None:
    """Single specialist mayor_data must not emit POV blocks."""
    mayor_data = [
        MayorData(
            source_agent="researcher",
            content="Research findings on cybersecurity topics.",
            pov=None,
        ),
    ]
    segments = build_pov_segments([], mayor_data, ["researcher"], False, False)
    assert segments == []


def test_build_pov_segments_multi_mayor_bypass() -> None:
    mayor_data = [
        MayorData(source_agent="art", content="Art lens content.", pov="Art"),
        MayorData(
            source_agent="ui_design",
            content="UI lens content.",
            pov="UI Design",
        ),
    ]
    segments = build_pov_segments([], mayor_data, ["art", "ui_design"], False, False)
    assert len(segments) == 2
    assert segments[0].pov == "Art"
    assert segments[1].pov == "UI Design"
    assert segments[0].source_agents == ["art"]


def test_build_pov_segments_merged_usable_falls_back_to_mayor() -> None:
    """L4 combiner may merge POVs into one thematic usable_answer — use mayor_data."""
    answers = [
        UsableAnswer(
            segment_id=str(uuid.uuid4()),
            order_hint=1,
            title="Aesthetic and Usability Guidelines",
            content="Combined merged answer from combiner.",
            source_agents=["art", "ui_design"],
        ),
    ]
    mayor_data = [
        MayorData(
            source_agent="art",
            content="Art-specific aesthetics: blue palette, Open Sans.",
            pov="Art",
        ),
        MayorData(
            source_agent="ui_design",
            content="UI-specific patterns: nav bar, touch targets.",
            pov="UI Design",
        ),
    ]
    segments = build_pov_segments(
        answers,
        mayor_data,
        ["art", "ui_design"],
        defense_ran=True,
        exhausted=False,
    )
    assert len(segments) == 2
    assert {s.pov for s in segments} == {"Art", "UI Design"}
    assert "blue palette" in segments[0].content
    assert "touch targets" in segments[1].content


def test_build_pov_segments_two_merged_themes_same_pov_falls_back() -> None:
    """Two usable segments that only cover one POV should still fall back."""
    answers = [
        UsableAnswer(
            segment_id=str(uuid.uuid4()),
            order_hint=1,
            title="Colors",
            content="Blue and green.",
            source_agents=["art"],
        ),
        UsableAnswer(
            segment_id=str(uuid.uuid4()),
            order_hint=2,
            title="Typography",
            content="Open Sans headings.",
            source_agents=["art"],
        ),
    ]
    mayor_data = [
        MayorData(source_agent="art", content="Art content.", pov="Art"),
        MayorData(source_agent="ui_design", content="UI content.", pov="UI Design"),
    ]
    segments = build_pov_segments(answers, mayor_data, ["art", "ui_design"], False, False)
    assert len(segments) == 2
    assert {s.pov for s in segments} == {"Art", "UI Design"}


def test_presenter_emits_pov_segments_and_done_stage() -> None:
    state = build_initial_state(
        "Design a science app UI covering aesthetics and usability",
        panel_id="seg-panel",
        chain_profile="L4",
    )
    state["active_agents"] = ["art", "ui_design"]
    state["combiners_bypassed"] = False
    state["usable_answers"] = [
        UsableAnswer(
            segment_id=str(uuid.uuid4()),
            order_hint=1,
            title="Aesthetics",
            content="Warm colors and visual hierarchy.",
            review_status="approved",
            source_agents=["art"],
        ),
        UsableAnswer(
            segment_id=str(uuid.uuid4()),
            order_hint=2,
            title="Usability",
            content="Large tap targets and clear nav.",
            review_status="approved",
            source_agents=["ui_design"],
        ),
    ]
    state["defense_reviews"] = []

    result = _run_presenter(state)
    panel = result["panels"][0]

    assert panel.status == "completed"
    assert panel.pipeline_stage == PipelineStage.DONE
    assert len(panel.pov_segments) == 2
    assert {s.pov for s in panel.pov_segments} == {"Art", "UI Design"}


def test_presenter_merged_usable_falls_back_to_mayor_segments() -> None:
    state = build_initial_state(
        "Design a science app UI covering aesthetics and usability",
        panel_id="merged-panel",
        chain_profile="L4",
    )
    state["active_agents"] = ["art", "ui_design"]
    state["combiners_bypassed"] = False
    state["usable_answers"] = [
        UsableAnswer(
            segment_id=str(uuid.uuid4()),
            order_hint=1,
            title="Aesthetic and Usability Guidelines",
            content="Merged combiner output.",
            review_status="approved",
            source_agents=["art", "ui_design"],
        ),
    ]
    state["mayor_data"] = [
        MayorData(source_agent="art", content="Art lens details.", pov="Art"),
        MayorData(source_agent="ui_design", content="UI lens details.", pov="UI Design"),
    ]
    state["defense_reviews"] = []

    result = _run_presenter(state)
    panel = result["panels"][0]

    assert len(panel.pov_segments) == 2
    assert {s.pov for s in panel.pov_segments} == {"Art", "UI Design"}
