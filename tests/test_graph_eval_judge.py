"""Judge leg unit layer — parser is loud, retry protocol is bounded, no LLM.

The parser must error on garbage, never silently pass: a judge that can't be
parsed is a failed judge leg, not a green one.
"""

import pytest

from scripts.graph_eval import __main__ as cli
from scripts.graph_eval.judge import (
    JudgeParseError,
    build_judge_messages,
    parse_judge_output,
)


# ---------------------------------------------------------------------------
# Parser — accepts only a well-formed score object.
# ---------------------------------------------------------------------------


def test_parse_accepts_plain_and_fenced_json():
    assert parse_judge_output('{"score": 8, "verdict": "good"}') == (8.0, "good")
    fenced = 'Here you go:\n```json\n{"score": 3, "verdict": "weak coverage"}\n```'
    assert parse_judge_output(fenced) == (3.0, "weak coverage")


@pytest.mark.parametrize(
    "raw",
    [
        "utter garbage with no json",
        '{"score": 8}',  # missing verdict
        '{"verdict": "nice"}',  # missing score
        '{"score": 8, "verdict": "ok", "extra": 1}',  # extra key
        '{"score": "eight", "verdict": "ok"}',  # non-numeric score
        '{"score": true, "verdict": "ok"}',  # bool is not a score
        '{"score": 11, "verdict": "ok"}',  # out of range
        '{"score": -1, "verdict": "ok"}',  # out of range
        '{"score": 8, "verdict": ""}',  # empty verdict
        '{"score": 8, "verdict": 42}',  # non-string verdict
        '{"score": 8, "verdict": "ok"',  # broken JSON
    ],
)
def test_parse_rejects_garbage_loudly(raw):
    with pytest.raises(JudgeParseError):
        parse_judge_output(raw)


def test_judge_messages_carry_prompt_answer_and_povs():
    messages = build_judge_messages("What is X?", "X is Y.", ["chemistry", "economics"])
    assert messages[0].role == "system"
    user = messages[1].content
    assert "What is X?" in user
    assert "X is Y." in user
    assert "chemistry, economics" in user


# ---------------------------------------------------------------------------
# Retry protocol — exactly the two covered flake classes, both directions.
# ---------------------------------------------------------------------------


def test_judge_band_flake_retries_when_structurals_green():
    assert cli.retry_eligible(structural_pass=True, judge_pass=False, chain_profile="L1")
    # A judge parse error (judge_pass None) is the same flake class.
    assert cli.retry_eligible(structural_pass=True, judge_pass=None, chain_profile="L1")


def test_structural_flake_retries_only_on_search_profiles():
    assert cli.retry_eligible(structural_pass=False, judge_pass=True, chain_profile="L3")
    assert cli.retry_eligible(structural_pass=False, judge_pass=False, chain_profile="L4")
    # Nothing external runs on non-search profiles — no retry there.
    assert not cli.retry_eligible(structural_pass=False, judge_pass=True, chain_profile="L1")
    assert not cli.retry_eligible(structural_pass=False, judge_pass=True, chain_profile="L2")


def test_full_pass_never_retries():
    assert not cli.retry_eligible(structural_pass=True, judge_pass=True, chain_profile="L4")
