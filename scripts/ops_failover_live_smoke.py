#!/usr/bin/env python3
"""
Live failover smoke: simulate-unhealthy → probe until switch → clear → recover.

Requires a control-plane host with OPS_ADMIN_TOKEN set and at least two
registered providers (e.g. Hetzner + a throwaway AWS Tess stack).

Usage:
  set OPS_SMOKE_BASE_URL=https://your-control-plane
  set OPS_ADMIN_TOKEN=...
  set OPS_SMOKE_PRIMARY=prov_hetzner_local
  set OPS_SMOKE_STANDBY=prov_aws
  python scripts/ops_failover_live_smoke.py

Exit 0 only if active provider flips to standby then can recover.
This exercises real HTTP timing / flap thresholds — not a substitute for unit tests,
but the bar for "I've broken this on purpose and watched it recover."
"""

from __future__ import annotations

import os
import sys
import time

import httpx

BASE = os.environ.get("OPS_SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.environ.get("OPS_ADMIN_TOKEN", "")
PRIMARY = os.environ.get("OPS_SMOKE_PRIMARY", "prov_hetzner_local")
STANDBY = os.environ.get("OPS_SMOKE_STANDBY", "prov_aws")
THRESHOLD = int(os.environ.get("OPS_SMOKE_FAILURE_THRESHOLD", "3"))
TIMEOUT = float(os.environ.get("OPS_SMOKE_TIMEOUT_SECONDS", "120"))


def _headers() -> dict[str, str]:
    if not TOKEN:
        print("OPS_ADMIN_TOKEN is required", file=sys.stderr)
        sys.exit(2)
    return {"Authorization": f"Bearer {TOKEN}"}


def _active(client: httpx.Client) -> str | None:
    r = client.get(f"{BASE}/ops/routing", headers=_headers())
    r.raise_for_status()
    return r.json()["routing"].get("active_provider_id")


def _probe(client: httpx.Client) -> dict:
    r = client.post(f"{BASE}/ops/probe", headers=_headers())
    r.raise_for_status()
    return r.json()


def main() -> int:
    print(f"Smoke against {BASE} primary={PRIMARY} standby={STANDBY}")
    with httpx.Client(timeout=30.0) as client:
        providers_body = client.get(f"{BASE}/ops/providers", headers=_headers()).json()
        if isinstance(providers_body, list):
            providers = providers_body
        elif isinstance(providers_body, dict):
            providers = providers_body.get("providers") or providers_body.get("items") or []
        else:
            providers = []
        ids = {p["id"] for p in providers if isinstance(p, dict)}
        if PRIMARY not in ids or STANDBY not in ids:
            print(
                f"Need both providers registered. Have: {sorted(ids)}",
                file=sys.stderr,
            )
            return 2

        start_active = _active(client)
        print(f"initial active={start_active}")

        # Ensure primary is active before breaking it
        if start_active != PRIMARY:
            r = client.post(
                f"{BASE}/ops/routing/active/{PRIMARY}",
                headers=_headers(),
            )
            r.raise_for_status()
            print(f"forced active -> {PRIMARY} (sessions may have dropped)")

        r = client.post(
            f"{BASE}/ops/providers/{PRIMARY}/simulate-unhealthy",
            params={"enabled": "true"},
            headers=_headers(),
        )
        r.raise_for_status()
        print(f"simulate-unhealthy enabled on {PRIMARY}")

        deadline = time.monotonic() + TIMEOUT
        switched = False
        probes = 0
        while time.monotonic() < deadline:
            body = _probe(client)
            probes += 1
            active = body["routing"]["active_provider_id"]
            failover = body.get("failover")
            print(
                f"  probe#{probes} active={active} "
                f"failover={bool(failover)} "
                f"failures={body['routing'].get('consecutive_failures')}"
            )
            if active == STANDBY:
                switched = True
                break
            if probes < THRESHOLD:
                time.sleep(0.2)
            else:
                time.sleep(1.0)

        if not switched:
            print("FAIL: did not failover to standby before timeout", file=sys.stderr)
            client.post(
                f"{BASE}/ops/providers/{PRIMARY}/simulate-unhealthy",
                params={"enabled": "false"},
                headers=_headers(),
            )
            return 1

        print(f"OK: failed over to {STANDBY} after {probes} probes")

        r = client.post(
            f"{BASE}/ops/providers/{PRIMARY}/simulate-unhealthy",
            params={"enabled": "false"},
            headers=_headers(),
        )
        r.raise_for_status()
        client.delete(f"{BASE}/ops/chaos/{PRIMARY}", headers=_headers())
        print(f"cleared simulate-unhealthy on {PRIMARY}")

        # Optional: force back for clean state (failback policy may not auto)
        r = client.post(
            f"{BASE}/ops/routing/active/{PRIMARY}",
            headers=_headers(),
        )
        r.raise_for_status()
        print(f"forced active back to {PRIMARY}")
        print("PASS: live simulate -> probe -> failover -> recover sequence completed")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
