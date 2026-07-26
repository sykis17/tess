"""Prometheus metrics + OpenTelemetry tracing for the ops/HA control plane.

Self-hosted, opt-in, **OFF by default** (toggles in ``app/core/config.py``; see
``deploy/MULTI_CLOUD.md``). Metrics are Prometheus pull; traces are OTLP/HTTP to a
self-hosted collector. No hosted/SaaS backend is ever called.

Cardinality discipline (enforced by ``tests/test_ops_metrics.py``): **every label value is
a fixed code enum or a per-process constant** — never user input, ids, URLs, or error
strings. ``record_*`` helpers are side-effect-free and MUST never raise — a metrics failure
must not perturb the fenced control path.

No import-time side effects beyond metric-object definition: HTTP servers, the ``/metrics``
mount, and the OTLP exporter are started only via the explicit ``init_*`` / ``start_*``
functions. The optional libraries degrade to no-ops if not installed.
"""

from __future__ import annotations

import contextvars
import functools
import inspect
import logging
import time
from typing import Any, Callable

from app.core.config import settings

logger = logging.getLogger(__name__)

# Set by the fence gate / endpoint when a request is refused for losing the fence, read by
# the mutation middleware to classify outcome=fenced_503. Belt-and-suspenders with
# request.state.ops_fenced (scope-backed) so classification is reliable regardless of how
# Starlette propagates request context.
_fenced_ctx: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "ops_request_fenced", default=False
)


def mark_fenced() -> None:
    _fenced_ctx.set(True)

# --- optional deps: degrade to no-op if not installed (observability is opt-in) ---
try:
    from prometheus_client import Counter, Gauge, Histogram, make_asgi_app, start_http_server

    _PROM_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the extra installed
    _PROM_AVAILABLE = False

try:
    from opentelemetry import propagate, trace

    _OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _OTEL_AVAILABLE = False


# Per-process constant. Each process only ever emits its own instance_id, so the
# fleet-wide series count for this label = number of CP processes (deployment-fixed).
INSTANCE_ID = settings.ops_cp_instance_id

# Recording is gated on this flag (set once from config). Metric OBJECTS are always defined
# when prometheus_client is importable, so tests can introspect label names regardless.
_METRICS_ON = bool(settings.ops_metrics_enabled and _PROM_AVAILABLE)

_DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

# ---------------------------------------------------------------------------
# Metric definitions (module-level singletons; no per-request allocation).
# ALL_METRICS lets the CI cardinality test introspect declared label names.
# ---------------------------------------------------------------------------
ALL_METRICS: list = []

if _PROM_AVAILABLE:
    # NOTE: prometheus_client appends `_total` to Counter names on exposition, so Counters
    # are declared WITHOUT the suffix here; they scrape as `tess_ops_*_total` as documented.
    ROLE_TRANSITIONS = Counter(
        "tess_ops_role_transitions",
        "CP role transitions (etcd election).",
        ["instance_id", "transition", "reason"],
    )
    IS_PRIMARY = Gauge(
        "tess_ops_is_primary",
        "1 when this instance currently holds the CP primary role, else 0.",
        ["instance_id"],
    )
    FENCE_TERM = Gauge(
        "tess_ops_fence_term",
        "Current fence term known to this instance (value, not a label).",
        ["instance_id"],
    )
    FENCE_REJECTS = Counter(
        "tess_ops_fence_rejects",
        "Writes/requests rejected because this node lost the fence.",
        ["instance_id", "kind", "surface"],
    )
    LEASE_KEEPALIVE = Counter(
        "tess_ops_lease_keepalive",
        "etcd lease keepalive outcomes while primary.",
        ["instance_id", "result"],
    )
    LEASE_TTL = Gauge(
        "tess_ops_lease_ttl_seconds",
        "Last observed etcd lease TTL (seconds).",
        ["instance_id"],
    )
    CAS_TOTAL = Counter(
        "tess_ops_cas",
        "Redis Lua compare-and-set outcomes on the fence term.",
        ["instance_id", "op", "result"],
    )
    MUTATIONS = Counter(
        "tess_ops_mutations",
        "Mutating /ops/* request outcomes.",
        ["instance_id", "outcome", "route"],
    )
    MUTATION_DURATION = Histogram(
        "tess_ops_mutation_duration_seconds",
        "Mutating /ops/* request duration (seconds).",
        ["instance_id", "outcome"],
        buckets=_DURATION_BUCKETS,
    )
    PROBES = Counter(
        "tess_ops_probes",
        "Provider health-probe outcomes (by provider TYPE, never provider_id).",
        ["provider_type", "result", "source"],
    )
    PROBE_DURATION = Histogram(
        "tess_ops_probe_duration_seconds",
        "Provider health-probe duration (seconds).",
        ["provider_type", "source"],
        buckets=_DURATION_BUCKETS,
    )
    FAILOVERS = Counter(
        "tess_ops_failovers",
        "Provider active-switch / failover outcomes (distinct from role transitions).",
        ["instance_id", "outcome", "mode"],
    )
    WORKER_TASK = Counter(
        "tess_ops_worker_task",
        "Celery ops-task outcomes (worker process).",
        ["task", "outcome"],
    )
    ALL_METRICS = [
        ROLE_TRANSITIONS, IS_PRIMARY, FENCE_TERM, FENCE_REJECTS, LEASE_KEEPALIVE,
        LEASE_TTL, CAS_TOTAL, MUTATIONS, MUTATION_DURATION, PROBES,
        PROBE_DURATION, FAILOVERS, WORKER_TASK,
    ]
else:  # pragma: no cover - names must exist for reference even without the lib
    ROLE_TRANSITIONS = IS_PRIMARY = FENCE_TERM = FENCE_REJECTS = None
    LEASE_KEEPALIVE = LEASE_TTL = CAS_TOTAL = MUTATIONS = None
    MUTATION_DURATION = PROBES = PROBE_DURATION = FAILOVERS = WORKER_TASK = None


def _safe(fn: Callable[..., None]) -> Callable[..., None]:
    """Wrap a recorder so a metrics failure never perturbs the control path."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> None:
        if not _METRICS_ON:
            return
        try:
            fn(*args, **kwargs)
        except Exception:  # never raise out of a recorder
            logger.debug("ops metric record failed", exc_info=True)

    return wrapper


# ---------------------------------------------------------------------------
# record_* helpers — the only way instrumentation touches metrics.
# ---------------------------------------------------------------------------
@_safe
def record_role_transition(transition: str, reason: str) -> None:
    ROLE_TRANSITIONS.labels(INSTANCE_ID, transition, reason).inc()


@_safe
def set_primary(is_primary: bool) -> None:
    IS_PRIMARY.labels(INSTANCE_ID).set(1 if is_primary else 0)


@_safe
def set_fence_term(term: int | None) -> None:
    if term is not None:
        FENCE_TERM.labels(INSTANCE_ID).set(term)


@_safe
def record_fence_reject(kind: str, surface: str) -> None:
    FENCE_REJECTS.labels(INSTANCE_ID, kind, surface).inc()


@_safe
def record_lease_keepalive(result: str) -> None:
    LEASE_KEEPALIVE.labels(INSTANCE_ID, result).inc()


@_safe
def set_lease_ttl(ttl_seconds: float) -> None:
    LEASE_TTL.labels(INSTANCE_ID).set(ttl_seconds)


@_safe
def record_cas(op: str, result: str) -> None:
    CAS_TOTAL.labels(INSTANCE_ID, op, result).inc()


@_safe
def record_mutation(outcome: str, route: str, duration_seconds: float | None = None) -> None:
    MUTATIONS.labels(INSTANCE_ID, outcome, route).inc()
    if duration_seconds is not None:
        MUTATION_DURATION.labels(INSTANCE_ID, outcome).observe(duration_seconds)


@_safe
def record_probe(provider_type: str, result: str, source: str, duration_seconds: float | None = None) -> None:
    PROBES.labels(provider_type, result, source).inc()
    if duration_seconds is not None:
        PROBE_DURATION.labels(provider_type, source).observe(duration_seconds)


@_safe
def record_failover(outcome: str, mode: str) -> None:
    FAILOVERS.labels(INSTANCE_ID, outcome, mode).inc()


@_safe
def record_worker_task(task: str, outcome: str) -> None:
    WORKER_TASK.labels(task, outcome).inc()


def fence_error_kind(exc: BaseException) -> str:
    """Map a FenceError subclass to a bounded ``kind`` label (never the message)."""
    from app.ops.fencing import FenceCasError, NotPrimaryError, PersistError

    if isinstance(exc, NotPrimaryError):
        return "not_primary"
    if isinstance(exc, FenceCasError):
        return "cas_stale"
    if isinstance(exc, PersistError):
        return "persist_error"
    return "persist_error"


# ---------------------------------------------------------------------------
# Worker task instrumentation — a decorator placed ABOVE the `def` (below
# @celery_app.task) so it stays outside the 800-char static-guard window in
# tests/test_ops_fencing.py and adds no banned substrings to app/worker.py.
# It re-raises unchanged (NotPrimaryError etc. must still propagate).
# ---------------------------------------------------------------------------
def ops_task_observed(task: str) -> Callable[[Callable], Callable]:
    def decorate(func: Callable) -> Callable:
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def awrapper(*args: Any, **kwargs: Any) -> Any:
                try:
                    result = await func(*args, **kwargs)
                except BaseException as exc:  # noqa: BLE001 - re-raised below
                    _record_task_failure(task, exc)
                    raise
                record_worker_task(task, "success")
                return result

            return awrapper

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                result = func(*args, **kwargs)
            except BaseException as exc:  # noqa: BLE001 - re-raised below
                _record_task_failure(task, exc)
                raise
            record_worker_task(task, "success")
            return result

        return wrapper

    return decorate


def _record_task_failure(task: str, exc: BaseException) -> None:
    from app.ops.fencing import NotPrimaryError

    outcome = "not_primary" if isinstance(exc, NotPrimaryError) else "error"
    record_worker_task(task, outcome)
    if outcome == "not_primary":
        record_fence_reject("not_primary", "worker_task")


# ---------------------------------------------------------------------------
# Tracing (OpenTelemetry). No-op unless tracing is active and the SDK is present.
# ---------------------------------------------------------------------------
_tracer_provider = None


class _NoopSpan:
    def set_attribute(self, *_a: Any, **_k: Any) -> None: ...
    def __enter__(self): return self
    def __exit__(self, *_a: Any) -> bool: return False


class _NoopTracer:
    def start_as_current_span(self, *_a: Any, **_k: Any) -> "_NoopSpan":
        return _NoopSpan()


def tracing_on() -> bool:
    return _OTEL_AVAILABLE and settings.ops_tracing_active()


def get_tracer():
    """Return an OTel tracer, or a no-op stub when OTel is unavailable."""
    if not _OTEL_AVAILABLE:
        return _NoopTracer()
    return trace.get_tracer("app.ops")


def extract_trace_context(headers: Any):
    """Extract W3C trace context (traceparent) from ASGI request headers, or None.

    ASGI scope headers are a list of ``(bytes, bytes)`` and already lower-cased; the W3C
    propagator looks up the STRING key ``traceparent``, so decode into a str→str carrier
    (a bytes-keyed dict would silently extract nothing → a broken trace).
    """
    if not _OTEL_AVAILABLE:
        return None
    try:
        carrier = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in headers
        }
        return propagate.extract(carrier)
    except Exception:  # pragma: no cover
        return None


def init_tracing(role: str) -> None:
    """Install a TracerProvider with an OTLP/HTTP exporter. Idempotent; guarded.

    ``role`` is a coarse constant (``web`` | ``worker``) recorded as a resource attribute.
    """
    global _tracer_provider
    if _tracer_provider is not None or not tracing_on():
        return
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import (
            ParentBased,
            TraceIdRatioBased,
        )

        ratio = max(0.0, min(1.0, settings.otel_traces_sampler_ratio))
        sampler = ParentBased(TraceIdRatioBased(ratio))
        resource = Resource.create(
            {
                "service.name": settings.otel_service_name,
                "service.instance.id": INSTANCE_ID,
                "ops.role_process": role,
            }
        )
        provider = TracerProvider(resource=resource, sampler=sampler)
        # Accept either a base endpoint or a full traces URL; the proto-http exporter
        # wants the full signal path, so append it when missing.
        endpoint = settings.otel_exporter_otlp_endpoint or ""
        if not endpoint.rstrip("/").endswith("/v1/traces"):
            endpoint = endpoint.rstrip("/") + "/v1/traces"
        # OTEL_BSP_SCHEDULE_DELAY (env) tunes flush latency; the obs overlay sets it low
        # so the harness spans file settles quickly.
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
        )
        trace.set_tracer_provider(provider)
        _tracer_provider = provider
        logger.warning(
            "ops tracing enabled role=%s endpoint=%s instance=%s",
            role, settings.otel_exporter_otlp_endpoint, INSTANCE_ID,
        )
    except Exception:  # never let observability init break startup
        logger.exception("failed to init ops tracing")


def shutdown_tracing() -> None:
    global _tracer_provider
    if _tracer_provider is not None:
        try:
            _tracer_provider.force_flush()
            _tracer_provider.shutdown()
        except Exception:  # pragma: no cover
            logger.debug("tracing shutdown failed", exc_info=True)
        _tracer_provider = None


# ---------------------------------------------------------------------------
# Exposition.
# ---------------------------------------------------------------------------
def prometheus_available() -> bool:
    return _PROM_AVAILABLE


def render_latest() -> tuple[bytes, str]:
    """Return (exposition bytes, content-type) for a direct GET /metrics route.

    A direct route (vs a mounted sub-app) serves at exactly ``/metrics`` with no 307
    redirect to ``/metrics/``.
    """
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return generate_latest(), CONTENT_TYPE_LATEST


def metrics_asgi_app():
    """ASGI sub-app exposing the Prometheus registry (kept for compatibility)."""
    if not _PROM_AVAILABLE:
        return None
    return make_asgi_app()


def start_worker_metrics_server() -> None:
    """Start the worker's Prometheus HTTP exposition (called once, post-fork).

    See §3a of the plan: relies on ``--concurrency=1`` so this binds exactly once in the
    single worker child, the same process that runs the ops tasks and increments counters.
    """
    if not (_METRICS_ON and _PROM_AVAILABLE):
        return
    try:
        start_http_server(settings.ops_metrics_worker_port)
        logger.warning(
            "ops worker metrics on :%s instance=%s",
            settings.ops_metrics_worker_port, INSTANCE_ID,
        )
    except Exception:  # pragma: no cover
        logger.exception("failed to start worker metrics server")


# ---------------------------------------------------------------------------
# /ops mutation observability middleware (pure ASGI; passes non-ops traffic straight
# through so /health, /ws, and the product path are untouched).
# ---------------------------------------------------------------------------
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class OpsObservabilityMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        method = scope.get("method", "")
        path = scope.get("path", "")
        if not (path.startswith("/ops/") and method in _MUTATING_METHODS):
            return await self.app(scope, receive, send)

        status_holder = {"code": 0}

        async def send_wrapper(message: Any) -> None:
            if message.get("type") == "http.response.start":
                status_holder["code"] = int(message.get("status", 0))
            await send(message)

        started = time.perf_counter()
        ctx = extract_trace_context(scope.get("headers") or [])
        req_id = _header_value(scope, b"x-ops-request-id")
        tracer = get_tracer()
        span_cm = (
            tracer.start_as_current_span("ops.http.mutation", context=ctx)
            if _OTEL_AVAILABLE and tracing_on()
            else tracer.start_as_current_span("ops.http.mutation")
        )
        token = _fenced_ctx.set(False)
        with span_cm as span:
            span.set_attribute("ops.instance_id", INSTANCE_ID)
            if req_id:
                span.set_attribute("ops.request_id", req_id)
            try:
                await self.app(scope, receive, send_wrapper)
            finally:
                status = status_holder["code"]
                fenced = _fenced_ctx.get() or bool(scope.get("state", {}).get("ops_fenced"))
                _fenced_ctx.reset(token)
                route = _route_template(scope)
                outcome = _classify_outcome(status, fenced)
                span.set_attribute("http.status_code", status)
                span.set_attribute("http.route", route)
                span.set_attribute("ops.outcome", outcome)
                span.set_attribute("ops.role", _current_role())
                record_mutation(outcome, route, time.perf_counter() - started)


def _header_value(scope: Any, name: bytes) -> str | None:
    for k, v in scope.get("headers") or []:
        if k == name:
            try:
                return v.decode("latin-1")
            except Exception:
                return None
    return None


def _route_template(scope: Any) -> str:
    route = scope.get("route")
    path_format = getattr(route, "path_format", None) or getattr(route, "path", None)
    return path_format or "__unmatched__"


def _classify_outcome(status: int, fenced: bool) -> str:
    if fenced:
        return "fenced_503"
    if 200 <= status < 300:
        return "success"
    if status in (401, 403, 503):
        return "auth_error"
    return "error"


def _current_role() -> str:
    try:
        from app.ops.fencing import get_role_state

        return get_role_state().role
    except Exception:  # pragma: no cover
        return "unknown"
