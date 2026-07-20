#!/usr/bin/env python3
"""
AWS standby wake/sleep helper for TESS multi-cloud ops.

Starts a stopped EC2 Tess stack, waits for /health, optionally runs the live
failover smoke test, then stops the instance again (even on failure).

Usage (local operator machine with AWS credentials):
  python scripts/aws_standby.py wake
  python scripts/aws_standby.py sleep
  python scripts/aws_standby.py cycle   # wake → health → smoke → sleep

Requires OPS_AWS_BASE_URL when Elastic IP is stable; falls back to patching
prov_aws on the control plane when the public IP drifts.
"""

from __future__ import annotations

import ipaddress
import os
import subprocess
import sys
import time
import warnings
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SMOKE_SCRIPT = _REPO_ROOT / "scripts" / "ops_failover_live_smoke.py"


def _load_local_env() -> None:
    """Load repo-root .env for local operator runs (does not override exported vars)."""
    try:
        from dotenv import load_dotenv

        load_dotenv(_REPO_ROOT / ".env", override=False)
    except ImportError:
        pass


_load_local_env()

INSTANCE_ID = os.environ.get("AWS_STANDBY_INSTANCE_ID", "i-0360ab28632a3c4a0")
REGION = os.environ.get("AWS_STANDBY_REGION", "us-east-2")
OPS_AWS_BASE_URL = os.environ.get("OPS_AWS_BASE_URL", "").rstrip("/")
OPS_SMOKE_BASE_URL = os.environ.get("OPS_SMOKE_BASE_URL", "").rstrip("/")
OPS_ADMIN_TOKEN = os.environ.get("OPS_ADMIN_TOKEN", "")
OPS_AWS_PROVIDER_ID = os.environ.get("OPS_AWS_PROVIDER_ID", "prov_aws")
AWS_BUDGET_NAME = os.environ.get("AWS_BUDGET_NAME", "")
AWS_BUDGET_ALERT_THRESHOLD = float(os.environ.get("AWS_BUDGET_ALERT_THRESHOLD", "0.80"))
HEALTH_TIMEOUT_S = int(os.environ.get("AWS_STANDBY_HEALTH_TIMEOUT_S", "180"))


class BudgetExceededError(RuntimeError):
    """AWS spend is near the configured budget alert threshold."""


def _ec2_client() -> Any:
    import boto3

    return boto3.client("ec2", region_name=REGION)


def _budgets_client() -> Any:
    import boto3

    return boto3.client("budgets", region_name="us-east-1")


def _sts_client() -> Any:
    import boto3

    return boto3.client("sts", region_name=REGION)


def _admin_headers() -> dict[str, str]:
    if not OPS_ADMIN_TOKEN:
        raise RuntimeError("OPS_ADMIN_TOKEN is required for control-plane mutations")
    return {"Authorization": f"Bearer {OPS_ADMIN_TOKEN}"}


def _host_from_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.hostname or url


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _base_url_for_host(host: str) -> str:
    if OPS_AWS_BASE_URL:
        parsed = urlparse(OPS_AWS_BASE_URL)
        scheme = parsed.scheme or "http"
        return f"{scheme}://{host}"
    return f"http://{host}"


def _health_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/health"


def _httpx_verify(base_url: str) -> bool:
    parsed = urlparse(base_url)
    if parsed.scheme == "https" and parsed.hostname and _is_ip_literal(parsed.hostname):
        return False
    return True


def check_budget(*, required: bool = False) -> None:
    """
    Abort if AWS spend is at or above the alert threshold.

    When AWS_BUDGET_NAME is unset: warn for wake, raise for cycle (required=True).
    """
    if not AWS_BUDGET_NAME:
        msg = (
            "AWS_BUDGET_NAME is not set — skipping budget guard. "
            "Set it to enable spend protection before wake/cycle."
        )
        if required:
            raise RuntimeError(msg)
        print(f"WARNING: {msg}")
        return

    try:
        account_id = _sts_client().get_caller_identity()["Account"]
        budget = _budgets_client().describe_budget(
            AccountId=account_id,
            BudgetName=AWS_BUDGET_NAME,
        )["Budget"]
        spent = float(budget["CalculatedSpend"]["ActualSpend"]["Amount"])
        limit = float(budget["BudgetLimit"]["Amount"])
    except Exception as exc:
        msg = f"Budget check failed for {AWS_BUDGET_NAME!r}: {exc}"
        if required:
            raise RuntimeError(msg) from exc
        print(f"WARNING: {msg}")
        return

    if limit <= 0:
        raise RuntimeError(f"Budget {AWS_BUDGET_NAME!r} has non-positive limit: {limit}")

    ratio = spent / limit
    print(
        f"AWS budget {AWS_BUDGET_NAME!r}: spent ${spent:.2f} / ${limit:.2f} "
        f"({ratio * 100:.1f}%, threshold {AWS_BUDGET_ALERT_THRESHOLD * 100:.0f}%)"
    )
    if ratio >= AWS_BUDGET_ALERT_THRESHOLD:
        raise BudgetExceededError(
            f"AWS spend ${spent:.2f} is at {ratio * 100:.1f}% of budget limit "
            f"${limit:.2f} (threshold {AWS_BUDGET_ALERT_THRESHOLD * 100:.0f}%). "
            "Refusing to start standby instance."
        )


def _describe_public_ip(ec2: Any | None = None) -> str:
    client = ec2 or _ec2_client()
    desc = client.describe_instances(InstanceIds=[INSTANCE_ID])
    public_ip = desc["Reservations"][0]["Instances"][0].get("PublicIpAddress")
    if not public_ip:
        raise RuntimeError(
            "No public IP yet — instance may still be booting network interfaces"
        )
    return public_ip


def resolve_host(public_ip: str) -> tuple[str, bool]:
    """
    Return (base_url, needs_ops_update).

    needs_ops_update is True when the control plane prov_aws URL must be patched.
    """
    if OPS_AWS_BASE_URL:
        registered_host = _host_from_url(OPS_AWS_BASE_URL)
        if registered_host == public_ip:
            return OPS_AWS_BASE_URL, False
        return _base_url_for_host(public_ip), True

    return f"http://{public_ip}", False


def update_ops_provider_base_url(base_url: str) -> None:
    if not OPS_SMOKE_BASE_URL:
        raise RuntimeError(
            "OPS_SMOKE_BASE_URL is required to patch prov_aws when the public IP drifts"
        )
    with httpx.Client(timeout=30.0) as client:
        r = client.patch(
            f"{OPS_SMOKE_BASE_URL}/ops/providers/{OPS_AWS_PROVIDER_ID}",
            headers=_admin_headers(),
            json={"base_url": base_url},
        )
        r.raise_for_status()
        print(f"Updated {OPS_AWS_PROVIDER_ID} base_url -> {base_url}")


def refresh_ops_provider(base_url: str) -> None:
    """Connect + probe so the control plane sees the standby as healthy."""
    if not OPS_SMOKE_BASE_URL:
        print("OPS_SMOKE_BASE_URL unset — skipping control-plane refresh")
        return
    with httpx.Client(timeout=60.0) as client:
        r = client.post(
            f"{OPS_SMOKE_BASE_URL}/ops/providers/{OPS_AWS_PROVIDER_ID}/connect",
            headers=_admin_headers(),
        )
        r.raise_for_status()
        body = r.json()
        print(
            f"connect {OPS_AWS_PROVIDER_ID}: connected={body.get('connected')} "
            f"http_ok={body.get('snapshot', {}).get('http_ok')}"
        )
        r = client.post(f"{OPS_SMOKE_BASE_URL}/ops/probe", headers=_admin_headers())
        r.raise_for_status()
        print("probe completed after standby wake")


def wait_healthy(base_url: str, timeout_s: int = HEALTH_TIMEOUT_S) -> None:
    url = _health_url(base_url)
    verify = _httpx_verify(base_url)
    if not verify:
        warnings.filterwarnings("ignore", message="Unverified HTTPS request")

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=5.0, verify=verify) as client:
                r = client.get(url)
            if r.status_code == 200 and r.json().get("status") == "ok":
                print(f"AWS stack healthy at {url}")
                return
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(5)

    raise TimeoutError(f"AWS stack did not report healthy within {timeout_s}s ({url})")


def wake(*, skip_budget: bool = False) -> str:
    if not skip_budget:
        check_budget(required=False)

    ec2 = _ec2_client()
    state = ec2.describe_instances(InstanceIds=[INSTANCE_ID])["Reservations"][0][
        "Instances"
    ][0]["State"]["Name"]
    if state == "stopped":
        print(f"Starting instance {INSTANCE_ID} in {REGION}...")
        ec2.start_instances(InstanceIds=[INSTANCE_ID])
        ec2.get_waiter("instance_running").wait(InstanceIds=[INSTANCE_ID])
    elif state == "running":
        print(f"Instance {INSTANCE_ID} already running")
    else:
        raise RuntimeError(f"Instance {INSTANCE_ID} is in state {state!r}, cannot wake")

    public_ip = _describe_public_ip(ec2)
    base_url, needs_update = resolve_host(public_ip)
    print(f"AWS instance running at {public_ip} (base_url={base_url})")

    if needs_update:
        update_ops_provider_base_url(base_url)

    return base_url


def sleep() -> None:
    ec2 = _ec2_client()
    state = ec2.describe_instances(InstanceIds=[INSTANCE_ID])["Reservations"][0][
        "Instances"
    ][0]["State"]["Name"]
    if state == "stopped":
        print(f"Instance {INSTANCE_ID} already stopped")
        return
    if state != "running":
        print(f"Instance {INSTANCE_ID} is {state!r}, skipping stop")
        return

    print(f"Stopping instance {INSTANCE_ID}...")
    ec2.stop_instances(InstanceIds=[INSTANCE_ID])
    ec2.get_waiter("instance_stopped").wait(InstanceIds=[INSTANCE_ID])
    print("AWS instance stopped")


def run_smoke() -> int:
    if not _SMOKE_SCRIPT.is_file():
        raise RuntimeError(f"Smoke script not found: {_SMOKE_SCRIPT}")
    print(f"Running {_SMOKE_SCRIPT.name}...")
    result = subprocess.run(
        [sys.executable, str(_SMOKE_SCRIPT)],
        cwd=str(_REPO_ROOT),
        check=False,
    )
    return int(result.returncode)


def cycle() -> int:
    exit_code = 1
    try:
        check_budget(required=True)
        base_url = wake(skip_budget=True)
        wait_healthy(base_url)
        refresh_ops_provider(base_url)
        exit_code = run_smoke()
    finally:
        try:
            sleep()
        except Exception as exc:
            print(f"ERROR during sleep: {exc}", file=sys.stderr)
            if exit_code == 0:
                exit_code = 1
    return exit_code


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    cmd = argv[0] if argv else "wake"

    try:
        if cmd == "wake":
            base_url = wake()
            wait_healthy(base_url)
            return 0
        if cmd == "sleep":
            sleep()
            return 0
        if cmd == "cycle":
            return cycle()
        print("usage: aws_standby.py [wake|sleep|cycle]", file=sys.stderr)
        return 2
    except BudgetExceededError as exc:
        print(f"BUDGET GUARD: {exc}", file=sys.stderr)
        return 2
    except (RuntimeError, TimeoutError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
