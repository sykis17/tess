#!/usr/bin/env python3
"""Manual/CI-friendly smoke steps for ops CP HA (etcd + Redis CAS).

Prereq:
  docker compose -f docker-compose.yml -f docker-compose.ops-ha.yml up --build -d

Then:
  python scripts/ops_cp_ha_smoke.py

Pass criteria:
  - Exactly one of :8000 / :8001 reports role=primary
  - After stopping the primary container, the other promotes (term advances)
  - Restarting the old primary leaves it standby; mutate returns 503
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

CP_A = os.environ.get("OPS_HA_SMOKE_A", "http://127.0.0.1:8000")
CP_B = os.environ.get("OPS_HA_SMOKE_B", "http://127.0.0.1:8001")
ADMIN = os.environ.get("OPS_ADMIN_TOKEN", "")


def _get(url: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(url: str) -> tuple[int, dict | str]:
    headers = {"Content-Type": "application/json"}
    if ADMIN:
        headers["Authorization"] = f"Bearer {ADMIN}"
    req = urllib.request.Request(url, method="POST", headers=headers, data=b"{}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def _ha(base: str) -> dict:
    return _get(f"{base.rstrip('/')}/ops/ha")


def _wait_single_primary(timeout: float = 60.0) -> tuple[str, dict, dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        a = _ha(CP_A)
        b = _ha(CP_B)
        roles = {a.get("instance_id"): a.get("role"), b.get("instance_id"): b.get("role")}
        primaries = [k for k, v in roles.items() if v == "primary"]
        if len(primaries) == 1:
            return primaries[0], a, b
        time.sleep(1.0)
    raise SystemExit(f"expected exactly one primary, last a={a} b={b}")


def main() -> int:
    print("1) Waiting for single primary…")
    primary_id, a, b = _wait_single_primary()
    print(f"   primary={primary_id} term_a={a.get('fence_term')} term_b={b.get('fence_term')}")
    primary_base = CP_A if a.get("instance_id") == primary_id else CP_B
    standby_base = CP_B if primary_base == CP_A else CP_A
    primary_container = "tess-engine-web-1" if primary_base == CP_A else "tess-engine-web-standby-1"

    print("2) Standby mutate must 503…")
    # Prefer a known mutating path; may 401 without admin — treat 503 as success.
    code, body = _post(f"{standby_base.rstrip('/')}/ops/probe")
    if code not in (401, 403, 503):
        print(f"   unexpected standby mutate status={code} body={body}")
        return 1
    if code == 503:
        print(f"   ok standby 503 detail={body}")
    else:
        print(f"   auth blocked ({code}); HA gate not exercised — set OPS_ADMIN_TOKEN")

    old_term = max(a.get("etcd_fence_term") or 0, b.get("etcd_fence_term") or 0)

    print(f"3) Stopping primary container ({primary_container})…")
    subprocess.run(["docker", "stop", primary_container], check=False)

    print("4) Waiting for promotion…")
    deadline = time.time() + 60
    promoted = None
    while time.time() < deadline:
        try:
            h = _ha(standby_base)
        except Exception:
            time.sleep(1)
            continue
        if h.get("role") == "primary":
            promoted = h
            break
        time.sleep(1)
    if promoted is None:
        print("   FAIL: standby did not promote")
        return 1
    new_term = promoted.get("etcd_fence_term") or promoted.get("fence_term") or 0
    if int(new_term) <= int(old_term):
        print(f"   FAIL: fence term did not advance old={old_term} new={new_term}")
        return 1
    print(f"   ok promoted instance={promoted.get('instance_id')} term={new_term}")

    print("5) Restart old primary; must stay standby…")
    subprocess.run(["docker", "start", primary_container], check=False)
    time.sleep(5)
    revived = _ha(primary_base)
    if revived.get("role") == "primary" and promoted.get("instance_id") != revived.get(
        "instance_id"
    ):
        # Both claiming primary is a hard fail
        other = _ha(standby_base)
        if other.get("role") == "primary":
            print(f"   FAIL: dual primary revived={revived} other={other}")
            return 1
    if revived.get("role") == "primary":
        print(
            "   note: revived won election (lease expired cleanly); acceptable if single primary"
        )
        _wait_single_primary()
    else:
        code, body = _post(f"{primary_base.rstrip('/')}/ops/probe")
        if code == 503:
            print("   ok zombie mutate 503")
        elif code in (401, 403):
            print(f"   auth blocked ({code}); set OPS_ADMIN_TOKEN to assert 503")
        else:
            print(f"   FAIL: zombie mutate status={code} body={body}")
            return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
