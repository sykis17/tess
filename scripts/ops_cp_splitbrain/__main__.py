"""CLI: python -m scripts.ops_cp_splitbrain run-all | run <id> | list"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Windows consoles often default to cp1252; keep harness output ASCII-safe.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Allow `python scripts/ops_cp_splitbrain/__main__.py` from repo root.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.ops_cp_splitbrain.config import load_config  # noqa: E402
from scripts.ops_cp_splitbrain.harness import ScenarioResult, run_scenario  # noqa: E402
from scripts.ops_cp_splitbrain.scenarios import ORDER, SCENARIOS  # noqa: E402


def _print_result(result) -> None:
    status = "SKIP" if result.skipped else ("PASS" if result.passed else "FAIL")
    print(f"[{status}] {result.scenario_id}  {result.title}  ({result.elapsed_s:.1f}s)")
    if result.skipped or not result.passed:
        print(f"         {result.detail}")


def _check_expectations(
    results: list[ScenarioResult],
    expect_pass: int | None,
    expect_skip: int | None,
) -> int:
    """Assert the expected tally as an exit-code artifact (never a log-grep).

    The offline verifier passes the topology-aware expectation (--expect-pass 10
    --expect-skip 1) so a silently shrunken suite or a blanket skip can never
    exit 0. Returns 0 on match (or no expectation), 1 on any mismatch.
    """
    rc = 0
    n_pass = sum(1 for r in results if r.passed)
    n_skip = sum(1 for r in results if r.skipped)
    if expect_pass is not None and n_pass != expect_pass:
        print(f"EXPECTATION FAILED: {n_pass} scenarios passed, expected {expect_pass}")
        rc = 1
    if expect_skip is not None and n_skip != expect_skip:
        print(f"EXPECTATION FAILED: {n_skip} scenarios skipped, expected {expect_skip}")
        rc = 1
    return rc


def _skip_result(mod, cfg) -> ScenarioResult | None:
    """Explicit topology skip, decided before any docker call; None = applicable."""
    reason = getattr(mod, "skip_reason", lambda _cfg: None)(cfg)
    if reason is None:
        return None
    return ScenarioResult(
        scenario_id=mod.ID,
        title=mod.TITLE,
        passed=False,
        detail=f"SKIP: {reason}",
        elapsed_s=0.0,
        skipped=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ops CP HA split-brain / degraded-consensus harness"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List scenarios")
    run_all_p = sub.add_parser(
        "run-all", help="Reset + run every scenario with clean baseline"
    )
    run_all_p.add_argument(
        "--expect-pass",
        type=int,
        default=None,
        help="Exit non-zero unless exactly N scenarios PASS (topology-aware tally gate)",
    )
    run_all_p.add_argument(
        "--expect-skip",
        type=int,
        default=None,
        help="Exit non-zero unless exactly N scenarios are SKIPPED",
    )
    run_p = sub.add_parser("run", help="Run one scenario")
    run_p.add_argument("scenario_id", choices=list(ORDER))

    args = parser.parse_args(argv)
    cfg = load_config()

    if args.cmd == "list":
        for sid in ORDER:
            mod = SCENARIOS[sid]
            print(f"{sid:28}  {mod.TITLE}")
        return 0

    if args.cmd == "run":
        mod = SCENARIOS[args.scenario_id]
        result = _skip_result(mod, cfg) or run_scenario(mod.ID, mod.TITLE, mod.run, cfg=cfg)
        _print_result(result)
        # An explicit skip is not a failure artifact.
        return 0 if (result.passed or result.skipped) else 1

    # run-all
    print(
        f"Harness config: ttl={cfg.lease_ttl_seconds}s "
        f"convergence={cfg.convergence_timeout}s project={cfg.project_name}"
    )
    results = []
    for sid in ORDER:
        mod = SCENARIOS[sid]
        print(f"\n=== {sid}: {mod.TITLE} ===")
        result = _skip_result(mod, cfg) or run_scenario(mod.ID, mod.TITLE, mod.run, cfg=cfg)
        _print_result(result)
        results.append(result)

    print("\n=== SUMMARY ===")
    for r in results:
        _print_result(r)
    failed = [r for r in results if not (r.passed or r.skipped)]
    skips = [r for r in results if r.skipped]
    applicable = len(results) - len(skips)
    tally = f"\n{applicable - len(failed)}/{applicable} PASS"
    if skips:
        reasons = "; ".join(
            f"{r.scenario_id} ({r.detail.removeprefix('SKIP: ')})" for r in skips
        )
        tally += f", {len(skips)} SKIPPED: {reasons}"
    print(tally)
    expect_rc = _check_expectations(results, args.expect_pass, args.expect_skip)
    return 1 if failed else expect_rc


if __name__ == "__main__":
    raise SystemExit(main())
