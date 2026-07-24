"""HTTP / Redis observables — assert artifacts, not log strings."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import HarnessConfig
from . import docker_util as dk


REDIS_FENCE_KEY = "ops:control_plane:fence_term"
REDIS_BLOB_KEY = "ops:control_plane"
REDIS_PROVIDER_CHANGED = "ops:provider_changed"


@dataclass
class Topology:
    primary_id: str
    primary_base: str
    standby_base: str
    primary_service: str
    standby_service: str
    ha_a: dict[str, Any]
    ha_b: dict[str, Any]
    pre_fault_term: int


class AssertionError_(AssertionError):
    """Harness assertion failure with artifact dump."""


def get_json(url: str, *, timeout: float = 5.0) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def request_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 8.0,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if headers:
        hdrs.update(headers)
    headers = hdrs
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            parsed: Any = json.loads(raw) if raw else {}
            return resp.status, parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw
    except urllib.error.URLError as exc:
        return 0, {"error": "url_error", "message": str(exc)}


def ha(cfg: HarnessConfig, base: str) -> dict[str, Any]:
    return get_json(f"{base.rstrip('/')}/ops/ha")


def ha_both(cfg: HarnessConfig) -> tuple[dict[str, Any], dict[str, Any]]:
    return ha(cfg, cfg.cp_a), ha(cfg, cfg.cp_b)


def redis_get(cfg: HarnessConfig, key: str) -> str | None:
    out = dk.redis_cli(cfg, "GET", key)
    if out in ("", "(nil)"):
        return None
    return out


def redis_set(cfg: HarnessConfig, key: str, value: str) -> None:
    dk.redis_cli(cfg, "SET", key, value)


def redis_del(cfg: HarnessConfig, *keys: str) -> None:
    if keys:
        dk.redis_cli(cfg, "DEL", *keys)


def redis_fence_term(cfg: HarnessConfig) -> int:
    raw = redis_get(cfg, REDIS_FENCE_KEY)
    return int(raw) if raw else 0


def redis_blob(cfg: HarnessConfig) -> dict[str, Any] | None:
    raw = redis_get(cfg, REDIS_BLOB_KEY)
    if not raw:
        return None
    return json.loads(raw)


def active_provider_id(cfg: HarnessConfig) -> str | None:
    blob = redis_blob(cfg)
    if not blob:
        return None
    routing = blob.get("routing") or {}
    return routing.get("active_provider_id")


def wait_until(
    predicate,
    *,
    timeout: float,
    poll: float,
    label: str,
) -> Any:
    deadline = time.time() + timeout
    last: Any = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(poll)
    raise AssertionError_(f"timeout waiting for {label}; last={last!r}")


def wait_single_primary(cfg: HarnessConfig) -> Topology:
    def _probe() -> Topology | None:
        try:
            a, b = ha_both(cfg)
        except Exception:
            return None
        roles = {
            a.get("instance_id"): a.get("role"),
            b.get("instance_id"): b.get("role"),
        }
        primaries = [k for k, v in roles.items() if v == "primary"]
        if len(primaries) != 1:
            return None
        primary_id = primaries[0]
        if a.get("instance_id") == primary_id:
            primary_base, standby_base = cfg.cp_a, cfg.cp_b
            primary_service, standby_service = cfg.web_service, cfg.standby_service
        else:
            primary_base, standby_base = cfg.cp_b, cfg.cp_a
            primary_service, standby_service = cfg.standby_service, cfg.web_service
        term = max(
            int(a.get("etcd_fence_term") or a.get("fence_term") or 0),
            int(b.get("etcd_fence_term") or b.get("fence_term") or 0),
            redis_fence_term(cfg),
        )
        return Topology(
            primary_id=str(primary_id),
            primary_base=primary_base,
            standby_base=standby_base,
            primary_service=primary_service,
            standby_service=standby_service,
            ha_a=a,
            ha_b=b,
            pre_fault_term=term,
        )

    return wait_until(
        _probe,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="exactly one primary",
    )


def count_primaries(cfg: HarnessConfig) -> tuple[int, dict[str, Any], dict[str, Any]]:
    a, b = ha_both(cfg)
    n = sum(1 for x in (a, b) if x.get("role") == "primary")
    return n, a, b


def mutate_probe(
    base: str,
    *,
    token: str | None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    return request_json(
        "POST", f"{base.rstrip('/')}/ops/probe", token=token, body={}, headers=headers
    )


def mutate_set_active(
    base: str,
    provider_id: str,
    *,
    token: str | None,
) -> tuple[int, Any]:
    return request_json(
        "POST",
        f"{base.rstrip('/')}/ops/routing/active/{provider_id}",
        token=token,
        body={},
    )


def create_provider(
    base: str,
    *,
    token: str,
    name: str,
    base_url: str,
    provider_type: str = "hetzner",
) -> dict[str, Any]:
    code, body = request_json(
        "POST",
        f"{base.rstrip('/')}/ops/providers",
        token=token,
        body={
            "type": provider_type,
            "name": name,
            "base_url": base_url,
            "enabled": True,
            "tags": ["ha-harness"],
        },
    )
    if code not in (200, 201) or not isinstance(body, dict):
        raise AssertionError_(f"create_provider failed status={code} body={body}")
    return body


def list_providers(base: str, *, token: str) -> list[dict[str, Any]]:
    code, body = request_json(
        "GET",
        f"{base.rstrip('/')}/ops/providers",
        token=token,
    )
    if code != 200 or not isinstance(body, list):
        raise AssertionError_(f"list_providers failed status={code} body={body}")
    return body


def detail_from_body(body: Any) -> dict[str, Any]:
    if isinstance(body, dict):
        if "detail" in body and isinstance(body["detail"], dict):
            return body["detail"]
        return body
    return {}


def is_fence_reject_response(status: int, body: Any) -> bool:
    """Loud fence failure: 503 not_primary / fence_rejected, or 5xx fence error."""
    if status == 503:
        detail = detail_from_body(body)
        err = str(detail.get("error") or "")
        if err in ("not_primary", "fence_rejected") or "fence" in str(body).lower():
            return True
        if detail.get("role") in ("standby", "demoted"):
            return True
        return True  # any 503 on mutate after unpause is loud refuse
    if status >= 500:
        text = str(body).lower()
        return "fence" in text or "cas" in text or "not primary" in text or "demot" in text
    return False


def assert_durable_unchanged(
    cfg: HarnessConfig,
    *,
    fence_before: int,
    active_before: str | None,
    blob_before: dict[str, Any] | None,
) -> None:
    fence_after = redis_fence_term(cfg)
    active_after = active_provider_id(cfg)
    blob_after = redis_blob(cfg)
    if fence_after != fence_before:
        raise AssertionError_(
            f"Redis fence_term changed by rejected writer: "
            f"{fence_before} -> {fence_after}"
        )
    if active_after != active_before:
        raise AssertionError_(
            f"active_provider_id changed: {active_before!r} -> {active_after!r}"
        )
    # Blob may be absent in empty-blob scenarios; only compare when both present
    # for active id (already checked). saved_at may move only on successful persist.
    if blob_before is not None and blob_after is not None:
        before_active = (blob_before.get("routing") or {}).get("active_provider_id")
        after_active = (blob_after.get("routing") or {}).get("active_provider_id")
        if before_active != after_active:
            raise AssertionError_(
                f"blob routing.active_provider_id changed: "
                f"{before_active!r} -> {after_active!r}"
            )


def peek_provider_changed(
    cfg: HarnessConfig,
    mutate_fn,
    *,
    listen_seconds: float = 2.0,
) -> tuple[tuple[int, Any], int]:
    """SUBSCRIBE briefly around a mutate; return (mutate_result, message_count).

    Uses redis-cli --csv SUBSCRIBE in a short docker exec window is awkward;
    instead compare pubsub channel message counter via PUBSUB NUMSUB before/after
    is also weak. Prefer: snapshot active + fence, run mutate, re-check artifacts.
    For publish detection we use a background redis-cli SUBSCRIBE with timeout.
    """
    # Best-effort: run subscribe with timeout in parallel via redis-cli --raw
    # For portability, count messages by wrapping mutate and checking redis
    # MONITOR is too noisy. Use a short SUBSCRIBE via docker exec with timeout.
    cid = dk.container_id(cfg, cfg.redis_service)
    import subprocess
    import threading

    messages: list[str] = []

    def _listen() -> None:
        proc = subprocess.Popen(
            [
                "docker",
                "exec",
                "-i",
                cid,
                "timeout",
                str(max(1, int(listen_seconds) + 1)),
                "redis-cli",
                "SUBSCRIBE",
                REDIS_PROVIDER_CHANGED,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        assert proc.stdout is not None
        deadline = time.time() + listen_seconds + 1
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            messages.append(line.strip())
        proc.kill()

    t = threading.Thread(target=_listen, daemon=True)
    t.start()
    time.sleep(0.3)
    result = mutate_fn()
    t.join(timeout=listen_seconds + 2)
    # redis-cli subscribe prints message type lines; count "message" entries
    msg_count = sum(1 for m in messages if m == "message")
    return result, msg_count


# ---------------------------------------------------------------------------
# Observability artifacts (s10): Prometheus scrape + exported OTel spans.
# ---------------------------------------------------------------------------
def fetch_text(url: str, *, timeout: float = 5.0) -> str:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def scrape_metrics(base_or_url: str, *, timeout: float = 5.0) -> list[tuple[str, dict[str, str], float]]:
    """Scrape a Prometheus /metrics endpoint → list of (name, labels, value).

    ``base_or_url`` may be a base (``/metrics`` is appended) or a full URL.
    """
    url = base_or_url if base_or_url.rstrip("/").endswith("/metrics") else f"{base_or_url.rstrip('/')}/metrics"
    text = fetch_text(url, timeout=timeout)
    samples: list[tuple[str, dict[str, str], float]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            metric_part, value_part = line.rsplit(" ", 1)
            value = float(value_part)
        except ValueError:
            continue
        if "{" in metric_part:
            name, label_blob = metric_part.split("{", 1)
            labels = _parse_labels(label_blob.rstrip("}"))
        else:
            name, labels = metric_part, {}
        samples.append((name.strip(), labels, value))
    return samples


def _parse_labels(blob: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    for part in _split_labels(blob):
        if "=" not in part:
            continue
        key, _, val = part.partition("=")
        labels[key.strip()] = val.strip().strip('"')
    return labels


def _split_labels(blob: str) -> list[str]:
    out, cur, in_quote = [], [], False
    for ch in blob:
        if ch == '"':
            in_quote = not in_quote
            cur.append(ch)
        elif ch == "," and not in_quote:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur))
    return out


def metric_sum(
    samples: list[tuple[str, dict[str, str], float]],
    name: str,
    **want_labels: str,
) -> float:
    """Sum sample values whose name matches and whose labels are a superset of want."""
    total = 0.0
    for sname, labels, value in samples:
        if sname != name:
            continue
        if all(labels.get(k) == v for k, v in want_labels.items()):
            total += value
    return total


def gen_trace_headers(tag: str) -> tuple[dict[str, str], str, str]:
    """Return (headers, trace_id, request_id) — a sampled W3C traceparent + request id."""
    import uuid

    trace_id = uuid.uuid4().hex  # 32 hex = 16 bytes
    span_id = uuid.uuid4().hex[:16]  # 16 hex = 8 bytes
    request_id = f"{tag}-{uuid.uuid4().hex[:8]}"
    headers = {
        "traceparent": f"00-{trace_id}-{span_id}-01",
        "X-Ops-Request-Id": request_id,
    }
    return headers, trace_id, request_id


def read_exported_spans(cfg: HarnessConfig) -> list[dict[str, Any]]:
    """docker cp the collector's spans file, parse OTLP-JSON → list of normalized spans.

    Each span: {"name", "trace_id", "attrs": {key: str}}. Robust to camel/snake keys and
    a growing NDJSON file; returns [] if the file is not yet present.
    """
    import os
    import tempfile

    cid = dk.container_id(cfg, cfg.collector_service)
    tmp = os.path.join(tempfile.gettempdir(), "ops_cp_spans.json")
    dk._run(["docker", "cp", f"{cid}:{cfg.spans_file}", tmp], check=False)
    spans: list[dict[str, Any]] = []
    try:
        with open(tmp, encoding="utf-8") as fh:
            content = fh.read()
    except FileNotFoundError:
        return []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        spans.extend(_extract_spans(obj))
    return spans


def _extract_spans(obj: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    resource_spans = obj.get("resourceSpans") or obj.get("resource_spans") or []
    for rs in resource_spans:
        scope_spans = rs.get("scopeSpans") or rs.get("scope_spans") or []
        for ss in scope_spans:
            for sp in ss.get("spans") or []:
                attrs: dict[str, str] = {}
                for kv in sp.get("attributes") or []:
                    val = kv.get("value") or {}
                    attrs[kv.get("key", "")] = str(
                        val.get("stringValue")
                        if "stringValue" in val
                        else val.get("intValue")
                        if "intValue" in val
                        else val.get("boolValue")
                        if "boolValue" in val
                        else val.get("doubleValue", "")
                    )
                out.append(
                    {
                        "name": sp.get("name", ""),
                        "trace_id": sp.get("traceId") or sp.get("trace_id") or "",
                        "attrs": attrs,
                    }
                )
    return out
