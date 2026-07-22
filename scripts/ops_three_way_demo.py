#!/usr/bin/env python3
"""
Stakeholder three-way chaos demo (ops walkthrough, not new engine features).

Wakes one standby (AWS or GCP), optionally pauses so you can show
/ops-status/, runs the live failover smoke (Hetzner simulate-unhealthy →
streak → flip), then recovers and sleeps the standby.

Usage (operator laptop with cloud credentials + OPS_ADMIN_TOKEN):
  python scripts/ops_three_way_demo.py aws
  python scripts/ops_three_way_demo.py gcp
  python scripts/ops_three_way_demo.py aws --guided   # pause between phases
  python scripts/ops_three_way_demo.py --print-runbook

Env (same as standby / smoke scripts):
  OPS_SMOKE_BASE_URL   control plane (default http://5.78.186.223)
  OPS_ADMIN_TOKEN      required for smoke
  OPS_SMOKE_PRIMARY    default prov_hetzner_local
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

_CONTROL_PLANE_DEFAULT = "http://5.78.186.223"
_OPS_STATUS_PATH = "/ops-status/"
_OPS_UI_PATH = "/ops-ui/"

# standby_key -> (provider_id, standby script relative path)
_STANDBYS: dict[str, tuple[str, str]] = {
    "aws": ("prov_aws", "scripts/aws_standby.py"),
    "gcp": ("prov_gcp", "scripts/gcp_standby.py"),
}


def resolve_standby(key: str) -> tuple[str, Path]:
    """Return (provider_id, absolute standby script path) for aws|gcp."""
    normalized = key.strip().lower()
    if normalized not in _STANDBYS:
        raise ValueError(
            f"Unknown standby {key!r}; choose one of: {', '.join(sorted(_STANDBYS))}"
        )
    provider_id, rel = _STANDBYS[normalized]
    script = _REPO_ROOT / rel
    if not script.is_file():
        raise FileNotFoundError(f"Standby script not found: {script}")
    return provider_id, script


def control_plane_base() -> str:
    return os.environ.get("OPS_SMOKE_BASE_URL", _CONTROL_PLANE_DEFAULT).rstrip("/")


def print_runbook(*, standby_key: str | None = None) -> None:
    """Print copy-pasteable stakeholder walkthrough steps."""
    base = control_plane_base()
    targets = [standby_key] if standby_key else list(_STANDBYS)
    print("=== Stakeholder three-way chaos demo ===")
    print()
    print("Resting state (before / after): Hetzner active; AWS + GCP stopped.")
    print(f"Ops status: {base}{_OPS_STATUS_PATH}")
    print(f"Ops UI:     {base}{_OPS_UI_PATH}")
    print()
    print("Scoring source of truth: GET /health self-report (cpu/mem).")
    print("GCP Cloud Monitoring / CloudWatch / Hetzner Cloud API: skipped.")
    print()
    for key in targets:
        provider_id, _ = resolve_standby(key)
        print(f"--- Path: {key} (standby={provider_id}) ---")
        print(f"1. Wake:   python scripts/{key}_standby.py wake")
        print(f"2. Show:   open {base}{_OPS_STATUS_PATH} (host metrics + providers)")
        print(
            "3. Fail:   simulate-unhealthy on Hetzner -> probe streak 1->2->3 "
            "-> active flips"
        )
        print("           (automated: python scripts/ops_failover_live_smoke.py")
        print(f"            with OPS_SMOKE_STANDBY={provider_id})")
        print("4. Clear:  clear chaos -> force Hetzner active")
        print(f"5. Sleep:  python scripts/{key}_standby.py sleep")
        print()
        print(f"One-shot:  python scripts/ops_three_way_demo.py {key}")
        print(f"Guided:    python scripts/ops_three_way_demo.py {key} --guided")
        print()


def _pause(message: str) -> None:
    print()
    print(f">> {message}")
    try:
        input("   Press Enter to continue... ")
    except EOFError:
        print("   (no TTY - continuing)")


def _run_standby_cmd(script: Path, cmd: str) -> int:
    print(f"Running {script.name} {cmd}...")
    result = subprocess.run(
        [sys.executable, str(script), cmd],
        cwd=str(_REPO_ROOT),
        check=False,
    )
    return int(result.returncode)


def _run_smoke(provider_id: str) -> int:
    smoke = _REPO_ROOT / "scripts" / "ops_failover_live_smoke.py"
    if not smoke.is_file():
        print(f"Smoke script not found: {smoke}", file=sys.stderr)
        return 1
    env = os.environ.copy()
    env.setdefault("OPS_SMOKE_BASE_URL", control_plane_base())
    env.setdefault("OPS_SMOKE_PRIMARY", "prov_hetzner_local")
    env["OPS_SMOKE_STANDBY"] = provider_id
    print(
        f"Running {smoke.name} "
        f"(primary={env['OPS_SMOKE_PRIMARY']} standby={provider_id})..."
    )
    result = subprocess.run(
        [sys.executable, str(smoke)],
        cwd=str(_REPO_ROOT),
        env=env,
        check=False,
    )
    return int(result.returncode)


def run_demo(standby_key: str, *, guided: bool = False) -> int:
    """Wake → (optional pause) → smoke → (optional pause) → sleep."""
    provider_id, script = resolve_standby(standby_key)
    base = control_plane_base()
    exit_code = 1

    print_runbook(standby_key=standby_key)
    if guided:
        _pause(f"Ready to wake {standby_key}. Confirm resting Hetzner-active first.")

    try:
        code = _run_standby_cmd(script, "wake")
        if code != 0:
            return code

        if guided:
            _pause(
                f"Open {base}{_OPS_STATUS_PATH} — confirm {provider_id} is up "
                "and host metrics (cpu/mem) are visible."
            )

        exit_code = _run_smoke(provider_id)

        if guided:
            _pause(
                f"Confirm active flipped to {provider_id} (then recovered to Hetzner). "
                f"Optional: glance at {base}{_OPS_UI_PATH}."
            )
    finally:
        sleep_code = _run_standby_cmd(script, "sleep")
        if sleep_code != 0 and exit_code == 0:
            exit_code = sleep_code

    if exit_code == 0:
        print("PASS: stakeholder demo completed; standby sleeping.")
    else:
        print(
            f"DONE with exit={exit_code}; verify resting state "
            "(Hetzner active, standbys stopped).",
            file=sys.stderr,
        )
    return exit_code


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(
            "usage: ops_three_way_demo.py {aws|gcp} [--guided]\n"
            "       ops_three_way_demo.py --print-runbook [aws|gcp]",
            file=sys.stderr,
        )
        return 2

    if argv[0] == "--print-runbook":
        key = argv[1] if len(argv) > 1 else None
        try:
            if key:
                resolve_standby(key)
            print_runbook(standby_key=key)
        except (ValueError, FileNotFoundError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        return 0

    standby_key = argv[0]
    guided = "--guided" in argv[1:]
    try:
        return run_demo(standby_key, guided=guided)
    except (ValueError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
