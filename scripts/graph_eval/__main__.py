"""CLI for the graph eval harness.

    python -m scripts.graph_eval list
    python -m scripts.graph_eval run <prompt_id>          # single prompt, no history
    python -m scripts.graph_eval run-all                  # full set (the acceptance command)
    python -m scripts.graph_eval run-all --set smoke --expect-pass 5

Prompts run strictly sequentially (the Ollama request lock serializes model
calls anyway); all prompts share one event loop.
"""

import os
import sys

# Hard set, NOT setdefault: an inherited GRAPH_METRICS_ENABLED=false would
# silently zero every token/latency/cost column. Must happen before any app.*
# import — settings and the metrics flag are both computed at import time.
os.environ["GRAPH_METRICS_ENABLED"] = "true"
os.environ["GRAPH_TRACING_ENABLED"] = "false"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from dataclasses import dataclass  # noqa: E402

import app.graph.observability as obs  # noqa: E402

from scripts.graph_eval import history  # noqa: E402
from scripts.graph_eval.config import EvalConfig, load_config, resolve_graph_identity  # noqa: E402
from scripts.graph_eval.golden import GoldenPrompt, load_set  # noqa: E402
from scripts.graph_eval.rubrics import evaluate_structural  # noqa: E402
from scripts.graph_eval.runner import run_prompt  # noqa: E402


@dataclass
class PromptOutcome:
    prompt_id: str
    chain_profile: str
    product_mode: str
    passed: bool
    structural_pass: bool
    failures: tuple[str, ...]
    judge_score: float | None
    judge_verdict: str | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    judge_prompt_tokens: int | None
    judge_completion_tokens: int | None
    judge_cost_usd: float | None
    latency_s: float
    outcome: str
    attempts: int


def _assert_ready() -> tuple[str, str]:
    """Refuse to measure zeros: the metrics feed must be live in-process."""
    if not obs._METRICS_ON:
        raise SystemExit(
            "graph metrics are OFF in this process (prometheus_client missing or "
            "flag not applied before app import) — refusing to record a zeroed run"
        )
    provider, model = resolve_graph_identity()
    print(f"graph identity: provider={provider} model={model}")
    return provider, model


def _check_expectations(outcomes: list[PromptOutcome], expect_pass: int | None) -> int:
    """Assert the expected pass tally as an exit-code artifact (never a log-grep)."""
    passed = sum(1 for o in outcomes if o.passed)
    print(f"TALLY: {passed}/{len(outcomes)} passed"
          + (f" (expected {expect_pass})" if expect_pass is not None else " (no expectation set)"))
    if expect_pass is not None and passed != expect_pass:
        print(f"EXPECTATION FAILED: passed={passed} expected={expect_pass}")
        return 1
    return 0


async def _run_one(gp: GoldenPrompt, cfg: EvalConfig) -> PromptOutcome:
    started = time.monotonic()

    def _progress(node: str) -> None:
        print(f"  [{time.monotonic() - started:7.1f}s] {node}", flush=True)

    result = await run_prompt(
        gp.prompt,
        chain_profile=gp.chain_profile,
        product_mode=gp.product_mode,
        progress=_progress,
    )
    structural = evaluate_structural(
        result.final_state,
        gp.rubric,
        wall_s=result.wall_s,
        total_tokens=result.delta.total_tokens,
    )
    failures = structural.failures
    if result.outcome != "success":
        failures = (*failures, f"graph run errored: {result.error}")
    return PromptOutcome(
        prompt_id=gp.id,
        chain_profile=gp.chain_profile,
        product_mode=gp.product_mode,
        passed=structural.passed and result.outcome == "success",
        structural_pass=structural.passed and result.outcome == "success",
        failures=failures,
        judge_score=None,
        judge_verdict=None,
        prompt_tokens=result.delta.prompt_tokens,
        completion_tokens=result.delta.completion_tokens,
        cost_usd=result.delta.cost_usd,
        judge_prompt_tokens=None,
        judge_completion_tokens=None,
        judge_cost_usd=None,
        latency_s=result.wall_s,
        outcome=result.outcome,
        attempts=1,
    )


async def _run_selected(prompts: list[GoldenPrompt], cfg: EvalConfig) -> list[PromptOutcome]:
    outcomes: list[PromptOutcome] = []
    for index, gp in enumerate(prompts, start=1):
        print(f"--- [{index}/{len(prompts)}] {gp.id} ({gp.chain_profile}/{gp.product_mode}) ---")
        outcome = await _run_one(gp, cfg)
        status = "PASS" if outcome.passed else "FAIL"
        print(f"  => {status} ({outcome.latency_s:.1f}s)")
        for failure in outcome.failures:
            print(f"     failure: {failure}")
        outcomes.append(outcome)
    return outcomes


def _print_table(outcomes: list[PromptOutcome]) -> None:
    header = (
        f"{'prompt_id':<26} {'profile':<7} {'mode':<8} {'struct':<6} {'judge':<5} "
        f"{'p_tok':>7} {'c_tok':>7} {'cost$':>8} {'wall_s':>7}"
    )
    print("\n" + header)
    print("-" * len(header))
    for o in outcomes:
        judge = f"{o.judge_score:.0f}" if o.judge_score is not None else "-"
        struct = "PASS" if o.structural_pass else "FAIL"
        print(
            f"{o.prompt_id:<26} {o.chain_profile:<7} {o.product_mode:<8} {struct:<6} {judge:<5} "
            f"{o.prompt_tokens:>7} {o.completion_tokens:>7} {o.cost_usd:>8.4f} {o.latency_s:>7.1f}"
        )
    total_p = sum(o.prompt_tokens for o in outcomes)
    total_c = sum(o.completion_tokens for o in outcomes)
    total_cost = sum(o.cost_usd for o in outcomes)
    total_wall = sum(o.latency_s for o in outcomes)
    print("-" * len(header))
    print(
        f"{'TOTAL':<26} {'':<7} {'':<8} {'':<6} {'':<5} "
        f"{total_p:>7} {total_c:>7} {total_cost:>8.4f} {total_wall:>7.1f}"
    )


def _record_history(
    outcomes: list[PromptOutcome],
    cfg: EvalConfig,
    *,
    set_name: str,
    set_version: str,
    graph_provider: str,
    graph_model: str,
    wall_s: float,
) -> str:
    run_id = history.new_run_id()
    commit, dirty = history.git_identity(_ROOT)
    judged = [o for o in outcomes if o.judge_score is not None]
    conn = history.open_history(cfg.db_path)
    try:
        history.record_run(
            conn,
            history.RunRow(
                run_id=run_id,
                ts_utc=history.utc_now_iso(),
                git_commit=commit,
                git_dirty=dirty,
                set_version=set_version,
                set_name=set_name,
                graph_provider=graph_provider,
                graph_model=graph_model,
                judge_provider=cfg.judge_provider if judged else None,
                judge_model=cfg.judge_model if judged else None,
                judge_prompt_version=None,
                prompts_total=len(outcomes),
                structural_passed=sum(1 for o in outcomes if o.structural_pass),
                judge_passed=None,
                prompt_tokens=sum(o.prompt_tokens for o in outcomes),
                completion_tokens=sum(o.completion_tokens for o in outcomes),
                cost_usd=sum(o.cost_usd for o in outcomes),
                judge_prompt_tokens=None,
                judge_completion_tokens=None,
                judge_cost_usd=None,
                wall_s=wall_s,
                result="pass" if all(o.passed for o in outcomes) else "fail",
            ),
        )
        for o in outcomes:
            history.record_prompt_result(
                conn,
                history.PromptRow(
                    run_id=run_id,
                    prompt_id=o.prompt_id,
                    chain_profile=o.chain_profile,
                    product_mode=o.product_mode,
                    structural_pass=o.structural_pass,
                    failures=json.dumps(list(o.failures)),
                    judge_score=o.judge_score,
                    judge_verdict=o.judge_verdict,
                    prompt_tokens=o.prompt_tokens,
                    completion_tokens=o.completion_tokens,
                    cost_usd=o.cost_usd,
                    judge_prompt_tokens=o.judge_prompt_tokens,
                    judge_completion_tokens=o.judge_completion_tokens,
                    judge_cost_usd=o.judge_cost_usd,
                    latency_s=o.latency_s,
                    outcome=o.outcome,
                    attempts=o.attempts,
                ),
            )
    finally:
        conn.close()
    return run_id


def _cmd_list() -> int:
    golden = load_set()
    print(f"set_version={golden.set_version}  prompts={len(golden.prompts)}")
    for gp in golden.prompts:
        tags = ",".join(gp.tags) or "-"
        sets = ",".join(gp.sets)
        print(f"  {gp.id:<26} {gp.chain_profile:<4} {gp.product_mode:<8} sets={sets:<11} tags={tags}")
    return 0


def _cmd_run(prompt_id: str) -> int:
    _assert_ready()
    cfg = load_config()
    golden = load_set()
    matches = [gp for gp in golden.prompts if gp.id == prompt_id]
    if not matches:
        print(f"unknown prompt id: {prompt_id}")
        return 1
    outcomes = asyncio.run(_run_selected(matches, cfg))
    _print_table(outcomes)
    return 0 if outcomes[0].passed else 1


def _cmd_run_all(set_name: str, expect_pass: int | None) -> int:
    graph_provider, graph_model = _assert_ready()
    cfg = load_config()
    golden = load_set()
    prompts = list(golden.subset(set_name))
    print(f"set={set_name} ({len(prompts)} prompts, set_version={golden.set_version})")
    started = time.monotonic()
    outcomes = asyncio.run(_run_selected(prompts, cfg))
    wall_s = time.monotonic() - started
    _print_table(outcomes)
    run_id = _record_history(
        outcomes,
        cfg,
        set_name=set_name,
        set_version=golden.set_version,
        graph_provider=graph_provider,
        graph_model=graph_model,
        wall_s=wall_s,
    )
    print(f"\nhistory: run_id={run_id} db={cfg.db_path}")
    expect_rc = _check_expectations(outcomes, expect_pass)
    failed = any(not o.passed for o in outcomes)
    return 1 if failed else expect_rc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.graph_eval")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list golden-set prompts")
    run_p = sub.add_parser("run", help="run a single prompt (triage; no history row)")
    run_p.add_argument("prompt_id")
    all_p = sub.add_parser("run-all", help="run a prompt set and record history")
    all_p.add_argument("--set", dest="set_name", choices=["smoke", "full"], default="full")
    all_p.add_argument("--expect-pass", type=int, default=None)
    args = parser.parse_args(argv)

    if args.cmd == "list":
        return _cmd_list()
    if args.cmd == "run":
        return _cmd_run(args.prompt_id)
    return _cmd_run_all(args.set_name, args.expect_pass)


if __name__ == "__main__":
    raise SystemExit(main())
