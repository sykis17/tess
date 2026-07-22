#!/usr/bin/env python3
"""
GCP standby wake/sleep helper for TESS multi-cloud ops.

Starts a stopped Compute Engine Tess stack, waits for /health, optionally runs
the live failover smoke test, then stops the instance again (even on failure).

Usage (local operator machine with GCP ADC or a service-account JSON key):
  python scripts/gcp_standby.py wake
  python scripts/gcp_standby.py sleep
  python scripts/gcp_standby.py cycle   # wake → health → smoke → sleep
  python scripts/gcp_standby.py drift-check  # alert if standby is running

Requires OPS_GCP_BASE_URL when the static IP is stable; falls back to patching
prov_gcp on the control plane when the public IP drifts.

Credentials (first match wins):
  1. GOOGLE_APPLICATION_CREDENTIALS → path to SA JSON key
  2. Env named by GCP_SERVICE_ACCOUNT_JSON / OPS credentials_ref → JSON string
     or path to a JSON key file
  3. Application Default Credentials (gcloud auth application-default login)

serviceAccountUser note:
  Stop/start is performed by the *ops* SA via the Compute Engine API. The VM
  itself does not need an attached service account. If the VM *does* run as a
  Compute SA, the ops SA also needs roles/iam.serviceAccountUser on that SA
  (or start fails with a 403). Workaround: detach the VM SA, or grant
  serviceAccountUser on the VM's SA to the ops principal.
"""

from __future__ import annotations

import ipaddress
import json
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

# GCE status values that mean the standby is correctly idle.
_DRIFT_OK_STATES = frozenset({"TERMINATED", "STOPPING"})
# Forgotten wake / cycle died before finally.
_DRIFT_FAIL_STATES = frozenset({"RUNNING", "STAGING", "PROVISIONING"})

_COMPUTE_SCOPE = "https://www.googleapis.com/auth/compute"
_COMPUTE_BASE = "https://compute.googleapis.com/compute/v1"


def _load_local_env() -> None:
    """Load repo-root .env for local operator runs (does not override exported vars)."""
    try:
        from dotenv import load_dotenv

        load_dotenv(_REPO_ROOT / ".env", override=False)
    except ImportError:
        pass


_load_local_env()

PROJECT_ID = os.environ.get("GCP_STANDBY_PROJECT_ID", "tess-503119")
ZONE = os.environ.get("GCP_STANDBY_ZONE", "us-central1-a")
INSTANCE_NAME = os.environ.get("GCP_STANDBY_INSTANCE_NAME", "tess-gcp-primary")
OPS_GCP_BASE_URL = os.environ.get("OPS_GCP_BASE_URL", "").rstrip("/")
OPS_SMOKE_BASE_URL = os.environ.get("OPS_SMOKE_BASE_URL", "").rstrip("/")
OPS_ADMIN_TOKEN = os.environ.get("OPS_ADMIN_TOKEN", "")
OPS_GCP_PROVIDER_ID = os.environ.get("OPS_GCP_PROVIDER_ID", "prov_gcp")
HEALTH_TIMEOUT_S = int(os.environ.get("GCP_STANDBY_HEALTH_TIMEOUT_S", "180"))
POLL_INTERVAL_S = float(os.environ.get("GCP_STANDBY_POLL_INTERVAL_S", "5"))
# When "1"/"true"/"yes", drift-check exits 0 even if the instance is running.
GCP_STANDBY_ALLOW_RUNNING = os.environ.get("GCP_STANDBY_ALLOW_RUNNING", "").strip().lower() in (
    "1",
    "true",
    "yes",
)


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
    if OPS_GCP_BASE_URL:
        parsed = urlparse(OPS_GCP_BASE_URL)
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


def preflight_adc() -> None:
    """
    Fail fast when no usable GCP credentials path is visible.

    User env GOOGLE_APPLICATION_CREDENTIALS often needs a *new* terminal after
    SetEnvironmentVariable. Hint the usual ops key path; do not block if ADC
    or JSON-in-env credentials_ref can still work.
    """
    gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if gac and Path(gac).is_file():
        print(f"preflight: GOOGLE_APPLICATION_CREDENTIALS={gac}")
        return
    if gac and not Path(gac).is_file():
        raise RuntimeError(
            f"GOOGLE_APPLICATION_CREDENTIALS is set to {gac!r} but the file "
            "is missing. Fix the path or open a new terminal after "
            "SetEnvironmentVariable. Expected ops key e.g. "
            r"C:\Users\jesse\.ssh\tess-gcp-ops-key.json"
        )

    for env_name in (
        os.environ.get("OPS_GCP_CREDENTIALS_REF", "GCP_SERVICE_ACCOUNT_JSON"),
        "GCP_SERVICE_ACCOUNT_JSON",
    ):
        raw = os.environ.get(env_name or "", "").strip()
        if not raw:
            continue
        if Path(raw).is_file() or raw.startswith("{"):
            print(f"preflight: using credentials from env {env_name}")
            return

    # ADC may still work (gcloud application-default); warn loudly.
    print(
        "preflight WARNING: GOOGLE_APPLICATION_CREDENTIALS unset. "
        "Will try Application Default Credentials. If auth fails, set "
        r"GOOGLE_APPLICATION_CREDENTIALS=C:\Users\jesse\.ssh\tess-gcp-ops-key.json "
        "in a new PowerShell session (User env vars need a fresh shell).",
        file=sys.stderr,
    )


def _credentials() -> Any:
    """Resolve ADC / service-account credentials for Compute Engine API calls."""
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account
    import google.auth

    scopes = [_COMPUTE_SCOPE]
    preflight_adc()
    gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if gac and Path(gac).is_file():
        creds = service_account.Credentials.from_service_account_file(gac, scopes=scopes)
        creds.refresh(Request())
        return creds

    # credentials_ref style: env var holds JSON content or a file path
    for env_name in (
        os.environ.get("OPS_GCP_CREDENTIALS_REF", "GCP_SERVICE_ACCOUNT_JSON"),
        "GCP_SERVICE_ACCOUNT_JSON",
    ):
        raw = os.environ.get(env_name or "", "").strip()
        if not raw:
            continue
        if Path(raw).is_file():
            creds = service_account.Credentials.from_service_account_file(
                raw, scopes=scopes
            )
            creds.refresh(Request())
            return creds
        if raw.startswith("{"):
            info = json.loads(raw)
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=scopes
            )
            creds.refresh(Request())
            return creds

    creds, _project = google.auth.default(scopes=scopes)
    if not getattr(creds, "valid", False):
        creds.refresh(Request())
    return creds


def _authorized_session() -> Any:
    from google.auth.transport.requests import AuthorizedSession

    return AuthorizedSession(_credentials())


def _instance_url() -> str:
    return (
        f"{_COMPUTE_BASE}/projects/{PROJECT_ID}/zones/{ZONE}/instances/{INSTANCE_NAME}"
    )


def _describe_instance(session: Any | None = None) -> dict[str, Any]:
    sess = session or _authorized_session()
    response = sess.get(_instance_url())
    if response.status_code == 404:
        raise RuntimeError(
            f"Instance {INSTANCE_NAME} not found in {PROJECT_ID}/{ZONE}"
        )
    if response.status_code >= 400:
        raise RuntimeError(
            f"DescribeInstances failed ({response.status_code}): {response.text[:500]}"
        )
    return response.json()


def _public_ip_from_instance(instance: dict[str, Any]) -> str | None:
    for nic in instance.get("networkInterfaces") or []:
        for access in nic.get("accessConfigs") or []:
            nat = access.get("natIP")
            if nat:
                return str(nat)
    return None


def _wait_for_status(
    target: str,
    *,
    timeout_s: int = HEALTH_TIMEOUT_S,
    session: Any | None = None,
) -> dict[str, Any]:
    sess = session or _authorized_session()
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = _describe_instance(sess)
        status = last.get("status")
        print(f"  instance status={status}")
        if status == target:
            return last
        time.sleep(POLL_INTERVAL_S)
    raise TimeoutError(
        f"Instance {INSTANCE_NAME} did not reach {target} within {timeout_s}s "
        f"(last={last.get('status')!r})"
    )


def _post_instance_action(action: str, session: Any | None = None) -> None:
    sess = session or _authorized_session()
    url = f"{_instance_url()}/{action}"
    response = sess.post(url)
    if response.status_code >= 400:
        body = response.text[:800]
        hint = ""
        if response.status_code == 403 and "serviceAccountUser" in body:
            hint = (
                " Hint: ops SA needs roles/iam.serviceAccountUser on the VM's "
                "service account, OR detach the VM SA so stop/start only needs "
                "compute.instances.start/stop."
            )
        raise RuntimeError(
            f"Compute {action} failed ({response.status_code}): {body}{hint}"
        )


def resolve_host(public_ip: str) -> tuple[str, bool]:
    """
    Return (base_url, needs_ops_update).

    needs_ops_update is True when the control plane prov_gcp URL must be patched.
    """
    if OPS_GCP_BASE_URL:
        registered_host = _host_from_url(OPS_GCP_BASE_URL)
        if registered_host == public_ip:
            return OPS_GCP_BASE_URL, False
        return _base_url_for_host(public_ip), True

    return f"http://{public_ip}", False


def update_ops_provider_base_url(base_url: str) -> None:
    if not OPS_SMOKE_BASE_URL:
        raise RuntimeError(
            "OPS_SMOKE_BASE_URL is required to patch prov_gcp when the public IP drifts"
        )
    with httpx.Client(timeout=30.0) as client:
        r = client.patch(
            f"{OPS_SMOKE_BASE_URL}/ops/providers/{OPS_GCP_PROVIDER_ID}",
            headers=_admin_headers(),
            json={"base_url": base_url},
        )
        r.raise_for_status()
        print(f"Updated {OPS_GCP_PROVIDER_ID} base_url -> {base_url}")


def refresh_ops_provider(base_url: str) -> None:
    """Connect + probe so the control plane sees the standby as healthy."""
    if not OPS_SMOKE_BASE_URL:
        print("OPS_SMOKE_BASE_URL unset — skipping control-plane refresh")
        return
    with httpx.Client(timeout=60.0) as client:
        connect_url = f"{OPS_SMOKE_BASE_URL}/ops/providers/{OPS_GCP_PROVIDER_ID}/connect"
        r = client.post(connect_url, headers=_admin_headers())
        if r.status_code == 405:
            raise RuntimeError(
                f"405 on {connect_url} — Caddy is not routing /ops/* to web. "
                "On Hetzner: ensure DOMAIN is a bare IP/hostname (no http://), "
                "confirm deploy/Caddyfile.active has 'handle /ops/*', then "
                "bash ./deploy/deploy.sh (or recreate the caddy container)."
            )
        r.raise_for_status()
        body = r.json()
        print(
            f"connect {OPS_GCP_PROVIDER_ID}: connected={body.get('connected')} "
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
                print(f"GCP stack healthy at {url}")
                return
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(5)

    raise TimeoutError(f"GCP stack did not report healthy within {timeout_s}s ({url})")


def wake() -> str:
    session = _authorized_session()
    instance = _describe_instance(session)
    status = instance.get("status")
    if status == "TERMINATED":
        print(f"Starting instance {INSTANCE_NAME} in {ZONE}...")
        _post_instance_action("start", session)
        instance = _wait_for_status("RUNNING", session=session)
    elif status == "RUNNING":
        print(f"Instance {INSTANCE_NAME} already running")
    else:
        raise RuntimeError(
            f"Instance {INSTANCE_NAME} is in state {status!r}, cannot wake"
        )

    public_ip = _public_ip_from_instance(instance)
    if not public_ip:
        # NAT IP can lag briefly after start
        deadline = time.time() + 60
        while time.time() < deadline and not public_ip:
            time.sleep(POLL_INTERVAL_S)
            instance = _describe_instance(session)
            public_ip = _public_ip_from_instance(instance)
    if not public_ip:
        raise RuntimeError(
            "No public IP yet — instance may still be attaching accessConfig"
        )

    base_url, needs_update = resolve_host(public_ip)
    print(f"GCP instance running at {public_ip} (base_url={base_url})")

    if needs_update:
        update_ops_provider_base_url(base_url)

    return base_url


def sleep() -> None:
    session = _authorized_session()
    instance = _describe_instance(session)
    status = instance.get("status")
    if status == "TERMINATED":
        print(f"Instance {INSTANCE_NAME} already stopped")
        return
    if status != "RUNNING":
        print(f"Instance {INSTANCE_NAME} is {status!r}, skipping stop")
        return

    print(f"Stopping instance {INSTANCE_NAME}...")
    _post_instance_action("stop", session)
    _wait_for_status("TERMINATED", session=session)
    print("GCP instance stopped")


def drift_check(*, allow_running: bool | None = None) -> int:
    """
    Alert-only check that the standby instance is stopped when it should be.

    Exit 0 if state is TERMINATED/STOPPING (or allow_running and RUNNING/...).
    Exit 1 if state is RUNNING/STAGING/PROVISIONING without allow_running.
    Exit 1 for unexpected states.

    Does not stop or start the instance.
    """
    allow = GCP_STANDBY_ALLOW_RUNNING if allow_running is None else allow_running
    instance = _describe_instance()
    status = str(instance.get("status") or "UNKNOWN")
    public_ip = _public_ip_from_instance(instance) or "-"

    print(
        f"drift-check: instance={INSTANCE_NAME} zone={ZONE} project={PROJECT_ID} "
        f"status={status} public_ip={public_ip}"
    )

    if status in _DRIFT_OK_STATES:
        print(f"OK: standby is {status} (expected idle)")
        return 0

    if status in _DRIFT_FAIL_STATES:
        if allow:
            print(
                f"OK: standby is {status} but GCP_STANDBY_ALLOW_RUNNING is set "
                "(intentional wake)"
            )
            return 0
        print(
            f"DRIFT: standby is {status} - expected TERMINATED. "
            "Alert only (no auto-stop). Run: python scripts/gcp_standby.py sleep",
            file=sys.stderr,
        )
        return 1

    print(
        f"DRIFT: standby is in unexpected state {status!r}",
        file=sys.stderr,
    )
    return 1


def run_smoke() -> int:
    if not _SMOKE_SCRIPT.is_file():
        raise RuntimeError(f"Smoke script not found: {_SMOKE_SCRIPT}")
    env = os.environ.copy()
    env.setdefault("OPS_SMOKE_STANDBY", OPS_GCP_PROVIDER_ID)
    env.setdefault("OPS_SMOKE_PRIMARY", "prov_hetzner_local")
    print(f"Running {_SMOKE_SCRIPT.name} (standby={env.get('OPS_SMOKE_STANDBY')})...")
    result = subprocess.run(
        [sys.executable, str(_SMOKE_SCRIPT)],
        cwd=str(_REPO_ROOT),
        env=env,
        check=False,
    )
    return int(result.returncode)


def cycle() -> int:
    exit_code = 1
    try:
        base_url = wake()
        wait_healthy(base_url)
        refresh_ops_provider(base_url)
        exit_code = run_smoke()
    except (RuntimeError, TimeoutError, httpx.HTTPError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        exit_code = 1
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
        if cmd in ("drift-check", "status"):
            return drift_check()
        print(
            "usage: gcp_standby.py [wake|sleep|cycle|drift-check]",
            file=sys.stderr,
        )
        return 2
    except (RuntimeError, TimeoutError, httpx.HTTPError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
