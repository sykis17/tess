"""Unit layer for the graph eval harness — no LLM, no docker, no Ollama.

Proves the pieces that must not be vacuous: the rubric engine fails wrong
transcripts (not just passes right ones), the tally checker rejects both
directions, the CLI wiring routes set selection and expectations to the exit
code, and the sqlite writer round-trips every identity field. The live-LLM
smoke/full runs are a local command (see scripts/graph_eval/README.md) — only
this no-LLM layer rides per-push CI.
"""

import asyncio
import json
import sqlite3

import pytest

import app.graph.observability as obs
from app.graph.schemas import MayorData, Panel, UsableAnswer

from scripts.graph_eval import __main__ as cli
from scripts.graph_eval import runner
from scripts.graph_eval.judge import JudgeResult
from scripts.graph_eval.golden import GoldenPrompt, GoldenSet, load_set
from scripts.graph_eval.metrics_delta import GraphDelta, compute_delta, take_snapshot
from scripts.graph_eval.rubrics import evaluate_structural


def _completed_state(**overrides):
    final_panel = Panel(
        panel_id="p1",
        folder_path="general_assistant",
        status="completed",
        content_type="markdown",
        content="A real answer with enough substance to count as content.",
    )
    processing = Panel(
        panel_id="p1",
        folder_path="general_assistant",
        status="processing",
        content_type="markdown",
        content="",
    )
    state = {
        "panels": [processing, final_panel],
        "mayor_data": [
            MayorData(source_agent="chemistry", content="chem output"),
            MayorData(source_agent="economics", content="econ output"),
        ],
        "usable_answers": [
            UsableAnswer(segment_id="s1", order_hint=1, title="t", content="c"),
        ],
        "collected_data": ["chem output"],
        "active_agents": ["chemistry", "economics"],
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# Rubric engine — must pass a right transcript AND fail wrong ones.
# ---------------------------------------------------------------------------


def test_rubric_right_transcript_passes():
    result = evaluate_structural(
        _completed_state(),
        {
            "expect_agents_all": ["chemistry"],
            "expect_agents_any": ["economics", "biology"],
            "min_mayor_data": 2,
            "min_usable_answers": 1,
            "expect_content_type": "markdown",
            "max_wall_s": 600,
            "max_total_tokens": 100_000,
        },
        wall_s=71.0,
        total_tokens=18_000,
    )
    assert result.passed
    assert result.failures == ()


def test_rubric_missing_completed_panel_fails():
    state = _completed_state()
    state["panels"] = [p for p in state["panels"] if p.status != "completed"]
    state["mayor_data"] = []
    state["usable_answers"] = []
    state["collected_data"] = []
    result = evaluate_structural(state, {}, wall_s=1.0, total_tokens=10)
    assert not result.passed
    assert any("no completed panel" in f for f in result.failures)
    assert any("content length" in f for f in result.failures)


def test_rubric_wrong_agents_fail():
    result = evaluate_structural(
        _completed_state(),
        {"expect_agents_all": ["biology"], "expect_agents_any": ["art", "ui_design"]},
        wall_s=1.0,
        total_tokens=10,
    )
    assert not result.passed
    assert any("expected agent missing: biology" in f for f in result.failures)
    assert any("none of expected agents ran" in f for f in result.failures)


def test_rubric_counts_and_ceilings_fail():
    result = evaluate_structural(
        _completed_state(),
        {
            "min_mayor_data": 5,
            "min_usable_answers": 3,
            "max_wall_s": 10,
            "max_total_tokens": 100,
        },
        wall_s=50.0,
        total_tokens=5_000,
    )
    assert not result.passed
    assert len(result.failures) == 4


def test_rubric_format_check_fails():
    result = evaluate_structural(
        _completed_state(),
        {"expect_content_format": "ranked_list"},
        wall_s=1.0,
        total_tokens=10,
    )
    assert not result.passed
    assert any("content_format" in f for f in result.failures)


def test_rubric_unknown_key_is_loud():
    with pytest.raises(ValueError, match="unknown rubric keys"):
        evaluate_structural(_completed_state(), {"max_walls": 10}, wall_s=1.0, total_tokens=1)


# ---------------------------------------------------------------------------
# Tally checker — both directions.
# ---------------------------------------------------------------------------


def _outcome(prompt_id: str, passed: bool) -> cli.PromptOutcome:
    return cli.PromptOutcome(
        prompt_id=prompt_id,
        chain_profile="L4",
        product_mode="auto",
        passed=passed,
        structural_pass=passed,
        failures=() if passed else ("boom",),
        judge_score=None,
        judge_verdict=None,
        prompt_tokens=10,
        completion_tokens=5,
        cost_usd=0.0,
        judge_prompt_tokens=None,
        judge_completion_tokens=None,
        judge_cost_usd=None,
        latency_s=0.1,
        outcome="success",
        attempts=1,
    )


def test_tally_match_and_no_expectation_pass():
    outcomes = [_outcome("a", True), _outcome("b", True), _outcome("c", False)]
    assert cli._check_expectations(outcomes, 2) == 0
    assert cli._check_expectations(outcomes, None) == 0


def test_tally_mismatch_fails_both_directions():
    outcomes = [_outcome("a", True), _outcome("b", False)]
    assert cli._check_expectations(outcomes, 2) == 1
    assert cli._check_expectations(outcomes, 0) == 1


# ---------------------------------------------------------------------------
# CLI wiring — argparse -> set selection -> gate -> history -> exit code,
# with a fake runner (no LLM).
# ---------------------------------------------------------------------------


def _golden_prompt(pid: str, sets: tuple[str, ...]) -> GoldenPrompt:
    return GoldenPrompt(
        id=pid,
        prompt=f"prompt {pid}",
        chain_profile="L4",
        product_mode="auto",
        tags=(),
        sets=sets,
        rubric={},
    )


def _fake_suite(monkeypatch, tmp_path, failing_ids=()):
    golden = GoldenSet(
        set_version="test-v1",
        notes="",
        prompts=(
            _golden_prompt("p1", ("smoke", "full")),
            _golden_prompt("p2", ("smoke", "full")),
            _golden_prompt("p3", ("full",)),
        ),
    )
    executed: list[str] = []

    async def fake_run_prompt(
        prompt_text, *, chain_profile, product_mode, timeout_s=None, progress=None
    ):
        pid = prompt_text.split()[-1]
        executed.append(pid)
        state = _completed_state()
        if pid in failing_ids:
            state["panels"] = []
            state["mayor_data"] = []
            state["usable_answers"] = []
            state["collected_data"] = []
        return runner.PromptRunResult(
            outcome="success",
            error="",
            wall_s=0.01,
            final_state=state,
            delta=GraphDelta(prompt_tokens=10, completion_tokens=5, cost_usd=0.0, llm_calls=1),
        )

    async def fake_judge(cfg, prompt_text, answer, expected_povs):
        return JudgeResult(
            score=9.0, verdict="solid", prompt_tokens=100, completion_tokens=20, cost_usd=0.0
        )

    monkeypatch.setattr(cli, "load_set", lambda: golden)
    monkeypatch.setattr(cli, "run_prompt", fake_run_prompt)
    monkeypatch.setattr(cli, "judge_answer", fake_judge)
    monkeypatch.setattr(cli, "_assert_ready", lambda: ("fakeprov", "fakemodel"))
    monkeypatch.setenv("GRAPH_EVAL_HISTORY_DB", str(tmp_path / "history.db"))
    return executed, tmp_path / "history.db"


def test_run_all_smoke_selection_and_expectation(monkeypatch, tmp_path):
    executed, _ = _fake_suite(monkeypatch, tmp_path)
    assert cli.main(["run-all", "--set", "smoke", "--expect-pass", "2"]) == 0
    assert executed == ["p1", "p2"]  # p3 is full-only and must not run


def test_run_all_defaults_to_full_set(monkeypatch, tmp_path):
    executed, _ = _fake_suite(monkeypatch, tmp_path)
    assert cli.main(["run-all", "--expect-pass", "3"]) == 0
    assert executed == ["p1", "p2", "p3"]


def test_run_all_wrong_expectation_flips_exit_code(monkeypatch, tmp_path):
    _fake_suite(monkeypatch, tmp_path)
    assert cli.main(["run-all", "--set", "smoke", "--expect-pass", "1"]) == 1


def test_run_all_structural_failure_dominates(monkeypatch, tmp_path):
    _fake_suite(monkeypatch, tmp_path, failing_ids={"p2"})
    # Even a "correct" expectation of 1 pass cannot turn a failed run green.
    assert cli.main(["run-all", "--set", "smoke", "--expect-pass", "1"]) == 1


def test_run_all_writes_history_with_identity(monkeypatch, tmp_path):
    _fake_suite(monkeypatch, tmp_path)
    assert cli.main(["run-all", "--set", "smoke"]) == 0
    conn = sqlite3.connect(tmp_path / "history.db")
    try:
        run = conn.execute(
            "SELECT set_name, set_version, graph_provider, graph_model, git_commit, "
            "prompts_total, structural_passed, result, judge_provider, judge_model, "
            "judge_prompt_version, judge_passed FROM runs"
        ).fetchone()
        assert run[:4] == ("smoke", "test-v1", "fakeprov", "fakemodel")
        assert len(run[4]) == 40  # a real git commit hash
        assert run[5:8] == (2, 2, "pass")
        # Judge identity must be populated whenever a judge scored the run.
        assert run[8] is not None and run[9] is not None and run[10] is not None
        assert run[11] == 2
        rows = conn.execute(
            "SELECT prompt_id, structural_pass, failures, judge_score FROM prompt_results "
            "ORDER BY prompt_id"
        ).fetchall()
        assert [(r[0], r[1]) for r in rows] == [("p1", 1), ("p2", 1)]
        assert all(json.loads(r[2]) == [] for r in rows)
        assert all(r[3] == 9.0 for r in rows)
    finally:
        conn.close()


def test_run_single_unknown_id(monkeypatch, tmp_path):
    _fake_suite(monkeypatch, tmp_path)
    assert cli.main(["run", "nope"]) == 1


def test_judge_flake_retry_recovers_and_is_recorded(monkeypatch, tmp_path):
    _fake_suite(monkeypatch, tmp_path)
    scores = iter([2.0, 9.0])  # first judge call misses the band, the re-run clears it

    async def flaky_judge(cfg, prompt_text, answer, expected_povs):
        return JudgeResult(
            score=next(scores), verdict="v", prompt_tokens=1, completion_tokens=1, cost_usd=0.0
        )

    monkeypatch.setattr(cli, "judge_answer", flaky_judge)
    outcome = asyncio.run(
        cli._run_one_with_retry(_golden_prompt("p1", ("full",)), cli.load_config(), 1)
    )
    assert outcome.passed
    assert outcome.attempts == 2


def test_judge_persistent_failure_is_real(monkeypatch, tmp_path):
    _fake_suite(monkeypatch, tmp_path)

    async def bad_judge(cfg, prompt_text, answer, expected_povs):
        return JudgeResult(
            score=2.0, verdict="v", prompt_tokens=1, completion_tokens=1, cost_usd=0.0
        )

    monkeypatch.setattr(cli, "judge_answer", bad_judge)
    outcome = asyncio.run(
        cli._run_one_with_retry(_golden_prompt("p1", ("full",)), cli.load_config(), 1)
    )
    # Two consecutive judge-band failures are real — no third attempt.
    assert not outcome.passed
    assert outcome.attempts == 2


# ---------------------------------------------------------------------------
# Runaway-chain guard — a hung graph becomes a red result, not a hung harness.
# ---------------------------------------------------------------------------


class _FakeGraph:
    def __init__(self, hang: bool):
        self._hang = hang

    def astream(self, state, stream_mode):
        hang = self._hang

        async def _gen():
            yield {"wide_receiver": {"current_task": "probe"}}
            if hang:
                await asyncio.sleep(3600)
            yield {"presenter": {}}

        return _gen()


def test_runner_timeout_aborts_hung_graph(monkeypatch):
    monkeypatch.setattr(runner, "compiled_graph", _FakeGraph(hang=True))
    result = asyncio.run(
        runner.run_prompt("x", chain_profile="L3", product_mode="auto", timeout_s=0.2)
    )
    assert result.outcome == "timeout"
    assert "runaway-chain guard" in result.error
    # State merged before the abort is preserved for the structural post-mortem.
    assert result.final_state.get("current_task") == "probe"


def test_runner_completes_within_ceiling(monkeypatch):
    monkeypatch.setattr(runner, "compiled_graph", _FakeGraph(hang=False))
    result = asyncio.run(
        runner.run_prompt("x", chain_profile="L3", product_mode="auto", timeout_s=5.0)
    )
    assert result.outcome == "success"


# ---------------------------------------------------------------------------
# Golden loader — malformed data fails loudly.
# ---------------------------------------------------------------------------


def _write_set(tmp_path, prompts):
    path = tmp_path / "set.json"
    path.write_text(
        json.dumps({"set_version": "v1", "notes": "", "prompts": prompts}),
        encoding="utf-8",
    )
    return path


def _prompt_dict(pid="p1", **overrides):
    entry = {
        "id": pid,
        "prompt": "hello",
        "chain_profile": "L4",
        "product_mode": "auto",
        "tags": [],
        "sets": ["smoke", "full"],
        "rubric": {},
    }
    entry.update(overrides)
    return entry


def test_loader_accepts_valid_set(tmp_path):
    golden = load_set(_write_set(tmp_path, [_prompt_dict()]))
    assert golden.set_version == "v1"
    assert golden.subset("smoke") == golden.prompts


def test_loader_rejects_bad_data(tmp_path):
    with pytest.raises(ValueError, match="duplicate id"):
        load_set(_write_set(tmp_path, [_prompt_dict(), _prompt_dict()]))
    with pytest.raises(ValueError, match="invalid chain_profile"):
        load_set(_write_set(tmp_path, [_prompt_dict(chain_profile="L9")]))
    with pytest.raises(ValueError, match="invalid product_mode"):
        load_set(_write_set(tmp_path, [_prompt_dict(product_mode="hacker")]))
    with pytest.raises(ValueError, match="unknown rubric keys"):
        load_set(_write_set(tmp_path, [_prompt_dict(rubric={"max_walls": 1})]))
    with pytest.raises(ValueError, match='must belong to "full"'):
        load_set(_write_set(tmp_path, [_prompt_dict(sets=["smoke"])]))
    with pytest.raises(ValueError, match="unknown keys"):
        load_set(_write_set(tmp_path, [_prompt_dict(extra="x")]))


# ---------------------------------------------------------------------------
# Metrics delta sampler — non-vacuous: real registry movement must show up.
# ---------------------------------------------------------------------------


def test_metrics_delta_sees_registry_movement():
    assert obs._PROM_AVAILABLE, "prometheus_client is a locked dependency"
    before = take_snapshot()
    obs.LLM_TOKENS.labels(node="ge_test_node", provider="p", model="m", kind="prompt").inc(7)
    obs.LLM_TOKENS.labels(node="ge_test_node", provider="p", model="m", kind="completion").inc(3)
    obs.NODE_DURATION.labels(node="ge_test_node", chain_profile="L4", product_mode="auto").observe(1.5)
    after = take_snapshot()
    delta = compute_delta(before, after)
    assert delta.prompt_tokens == 7
    assert delta.completion_tokens == 3
    assert delta.total_tokens == 10
    assert delta.node_duration_s.get("ge_test_node") == pytest.approx(1.5)


def test_metrics_delta_zero_when_quiet():
    before = take_snapshot()
    delta = compute_delta(before, take_snapshot())
    assert delta.total_tokens == 0
    assert delta.llm_calls == 0
