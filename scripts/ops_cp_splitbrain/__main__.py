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
from scripts.ops_cp_splitbrain.harness import run_scenario  # noqa: E402
from scripts.ops_cp_splitbrain.scenarios import ORDER, SCENARIOS  # noqa: E402


def _print_result(result) -> None:
    status = "PASS" if result.passed else "FAIL"
    print(f"[{status}] {result.scenario_id}  {result.title}  ({result.elapsed_s:.1f}s)")
    if not result.passed:
        print(f"         {result.detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ops CP HA split-brain / degraded-consensus harness"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List scenarios")
    sub.add_parser("run-all", help="Reset + run every scenario with clean baseline")
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
        result = run_scenario(mod.ID, mod.TITLE, mod.run, cfg=cfg)
        _print_result(result)
        return 0 if result.passed else 1

    # run-all
    print(
        f"Harness config: ttl={cfg.lease_ttl_seconds}s "
        f"convergence={cfg.convergence_timeout}s project={cfg.project_name}"
    )
    results = []
    for sid in ORDER:
        mod = SCENARIOS[sid]
        print(f"\n=== {sid}: {mod.TITLE} ===")
        result = run_scenario(mod.ID, mod.TITLE, mod.run, cfg=cfg)
        _print_result(result)
        results.append(result)

    print("\n=== SUMMARY ===")
    for r in results:
        _print_result(r)
    failed = [r for r in results if not r.passed]
    print(f"\n{len(results) - len(failed)}/{len(results)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
