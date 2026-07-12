"""Tests for combiner schema parsing and serialization."""

import json
import uuid

from app.graph.combiner_utils import (
    _fallback_micro_data,
    _fallback_usable_answers,
    normalize_micro_data,
    parse_micro_data_json,
    parse_usable_answers_json,
    serialize_micro_data_for_llm,
)
from app.graph.schemas import MayorData, MicroData, MicroDataSegment


def test_micro_data_segment_accepts_overlap_notes() -> None:
    segment = MicroDataSegment(
        title="Shared palette",
        content="- Blue primary\n- Open Sans",
        source_agents=["art", "ui_design"],
        overlap_notes="Art and ui_design both recommend a calming blue palette.",
    )
    assert segment.overlap_notes is not None
    assert "art" in segment.source_agents


def test_normalize_micro_data_fills_missing_segment_sources() -> None:
    mayor_data = [
        MayorData(source_agent="art", content="Art content", pov="Art"),
        MayorData(source_agent="ui_design", content="UI content", pov="UI Design"),
    ]
    micro = MicroData(
        segments=[
            MicroDataSegment(title="Art slice", content="bullets"),
            MicroDataSegment(title="UI slice", content="bullets"),
        ],
        source_agents=[],
    )
    normalized = normalize_micro_data(micro, mayor_data, ["art", "ui_design"])
    assert normalized.segments[0].source_agents == ["art"]
    assert normalized.segments[1].source_agents == ["ui_design"]
    assert normalized.source_agents == ["art", "ui_design"]


def test_fallback_micro_data_one_segment_per_source() -> None:
    mayor_data = [
        MayorData(source_agent="art", content="Art inventory", pov="Art"),
        MayorData(source_agent="ui_design", content="UI inventory", pov="UI Design"),
    ]
    micro = _fallback_micro_data(mayor_data, ["art", "ui_design"])
    assert len(micro.segments) == 2
    assert micro.segments[0].source_agents == ["art"]
    assert micro.segments[1].source_agents == ["ui_design"]


def test_serialize_micro_data_includes_overlap_notes() -> None:
    micro = MicroData(
        segments=[
            MicroDataSegment(
                title="Typography",
                content="- Open Sans",
                source_agents=["art", "ui_design"],
                overlap_notes="Both lenses agree on Open Sans.",
            )
        ],
        source_agents=["art", "ui_design"],
    )
    text = serialize_micro_data_for_llm(micro)
    assert "Overlap:" in text
    assert "Open Sans" in text
    assert "Art" in text


def test_parse_micro_data_json_with_per_segment_sources() -> None:
    payload = json.dumps(
        {
            "combiner": "mayor",
            "segments": [
                {
                    "title": "Visual mood (Art POV)",
                    "content": "- Stars in background",
                    "source_agents": ["art"],
                    "overlap_notes": None,
                },
                {
                    "title": "Accessibility (UI Design POV)",
                    "content": "- WCAG contrast",
                    "source_agents": ["ui_design"],
                    "overlap_notes": None,
                },
            ],
            "source_agents": ["art", "ui_design"],
        }
    )
    mayor_data = [
        MayorData(source_agent="art", content="raw", pov="Art"),
        MayorData(source_agent="ui_design", content="raw", pov="UI Design"),
    ]
    micro = parse_micro_data_json(payload, mayor_data, ["art", "ui_design"])
    assert micro.segments[0].source_agents == ["art"]
    assert micro.segments[1].source_agents == ["ui_design"]


def test_fallback_usable_answers_prepends_overlap_notes() -> None:
    micro = MicroData(
        segments=[
            MicroDataSegment(
                title="Consensus palette",
                content="Use blue and white.",
                source_agents=["art", "ui_design"],
                overlap_notes="Multiple sources confirm a blue-forward palette.",
            )
        ],
        source_agents=["art", "ui_design"],
    )
    answers = _fallback_usable_answers(micro)
    assert len(answers) == 1
    assert "Multiple sources confirm" in answers[0].content
    assert answers[0].source_agents == ["art", "ui_design"]


def test_parse_usable_answers_json_carries_source_agents() -> None:
    segment_id = str(uuid.uuid4())
    payload = json.dumps(
        {
            "usable_answers": [
                {
                    "segment_id": segment_id,
                    "order_hint": 1,
                    "title": "Overview",
                    "content": "Multiple sources confirm a clean grid layout.",
                    "review_status": "pending",
                    "source_agents": ["art", "ui_design"],
                }
            ]
        }
    )
    micro = MicroData(segments=[], source_agents=["art", "ui_design"])
    answers = parse_usable_answers_json(payload, micro)
    assert answers[0].source_agents == ["art", "ui_design"]
