"""Prometheus metrics + OpenTelemetry tracing for the product graph (W2).

Deliberately separate from ``app/ops/metrics.py`` (which stays ops/HA-scoped): the graph
has its own flags — ``GRAPH_METRICS_ENABLED`` / ``GRAPH_TRACING_ENABLED``, both **OFF by
default** — so enabling ops observability never silently starts paying graph
instrumentation cost, and vice versa. Transport is shared: the same OTLP endpoint settings
and the same worker ``:9109`` Prometheus exposition (one default registry serves both).

Cardinality discipline (enforced by ``tests/test_graph_metrics.py``): every metric label
value is a fixed code enum, config-bounded, or a per-process constant. ``session_id`` /
``panel_id`` / URLs / error strings are span attributes only — **never** metric labels.
Unknown ``chain_profile`` / ``product_mode`` values fold to ``"other"``. The ``provider``
label is admitted here (unlike ops, where it shadows unbounded multi-cloud provider
records) strictly as the bounded ``LLMProvider`` enum value.

Duration-histogram outcome policy: histograms record **only when outcome == "success"** —
interrupted/errored/cancelled runs are short by definition and would pollute latency
trends in the flattering direction; the counters carry the outcome split. No ``outcome``
label on histograms (cardinality).

``record_*`` helpers and the wrappers never raise — a metrics failure must not perturb a
graph run. With all flags off, ``instrument_node`` is a single boolean check + passthrough.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import logging
import time
from typing import Any, Awaitable, Callable

from app.core.chain_profiles import ChainProfile
from app.core.config import settings
from app.core.product_modes import ProductMode
from app.core.session_control import SessionInterrupted
from app.graph.model_costs import cost_usd

logger = logging.getLogger(__name__)

# --- optional deps: degrade to no-op if not installed (observability is opt-in) ---
try:
    from prometheus_client import Counter, Histogram, start_http_server

    _PROM_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the extra installed
    _PROM_AVAILABLE = False

try:
    from opentelemetry import trace

    _OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _OTEL_AVAILABLE = False


# Recording is gated on this flag (set once from config). Metric OBJECTS are always
# defined when prometheus_client is importable, so tests can introspect label names.
_METRICS_ON = bool(settings.graph_metrics_enabled and _PROM_AVAILABLE)

# Bounded label domains; anything else folds to "other" (insurance against label
# explosion from a future config typo — guard-tested).
_CHAIN_PROFILES = frozenset(p.value for p in ChainProfile)
_PRODUCT_MODES = frozenset(m.value for m in ProductMode)

# W3: run-outcome vocabulary — the graph plane's first outcome bounding
# (before this, record_run piped free-form strings straight into a label).
# "resumed" = a resume-after-interrupt run that completed cleanly; it advances
# the counter but never the success-only duration histogram (partial wall time
# would flatter latency trends).
GRAPH_RUN_OUTCOMES = frozenset(
    {"success", "interrupted", "cancelled", "error", "resumed"}
)

# Which node is executing, for LLM-call attribution. Set by instrument_node; inherited
# by tasks the node spawns (contextvars propagate into asyncio.create_task).
_current_node: contextvars.ContextVar[str] = contextvars.ContextVar(
    "graph_current_node", default="unknown"
)

_RUN_BUCKETS = (1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, 900.0)
_NODE_BUCKETS = (0.1, 0.5, 1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0)
_LLM_BUCKETS = (0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0)

# ---------------------------------------------------------------------------
# Metric definitions (module-level singletons; no per-request allocation).
# ALL_GRAPH_METRICS lets the guard twin introspect declared label names.
# ---------------------------------------------------------------------------
ALL_GRAPH_METRICS: list = []

if _PROM_AVAILABLE:
    # Counters are declared WITHOUT the `_total` suffix (prometheus_client appends it).
    GRAPH_RUNS = Counter(
        "tess_graph_runs",
        "Graph pipeline runs by outcome.",
        ["chain_profile", "product_mode", "outcome"],
    )
    RUN_DURATION = Histogram(
        "tess_graph_run_duration_seconds",
        "Graph run duration (seconds); successful runs only.",
        ["chain_profile", "product_mode"],
        buckets=_RUN_BUCKETS,
    )
    NODE_RUNS = Counter(
        "tess_graph_node_runs",
        "Per-node executions by outcome.",
        ["node", "chain_profile", "product_mode", "outcome"],
    )
    NODE_DURATION = Histogram(
        "tess_graph_node_duration_seconds",
        "Per-node execution duration (seconds); successful executions only.",
        ["node", "chain_profile", "product_mode"],
        buckets=_NODE_BUCKETS,
    )
    LLM_CALLS = Counter(
        "tess_graph_llm_calls",
        "LLM provider calls by outcome (provider = bounded LLMProvider enum).",
        ["node", "provider", "model", "outcome"],
    )
    LLM_DURATION = Histogram(
        "tess_graph_llm_duration_seconds",
        "LLM call duration (seconds); successful calls only. For Ollama this includes "
        "the serialization-lock wait (queue time), not just inference.",
        ["provider", "model"],
        buckets=_LLM_BUCKETS,
    )
    LLM_TOKENS = Counter(
        "tess_graph_llm_tokens",
        "LLM tokens by kind (prompt|completion).",
        ["node", "provider", "model", "kind"],
    )
    LLM_COST = Counter(
        "tess_graph_llm_cost_usd",
        "Estimated LLM spend (USD); incremented only when cost > 0 (local models are 0).",
        ["node", "provider", "model"],
    )
    ALL_GRAPH_METRICS = [
        GRAPH_RUNS, RUN_DURATION, NODE_RUNS, NODE_DURATION,
        LLM_CALLS, LLM_DURATION, LLM_TOKENS, LLM_COST,
    ]
else:  # pragma: no cover - names must exist for reference even without the lib
    GRAPH_RUNS = RUN_DURATION = NODE_RUNS = NODE_DURATION = None
    LLM_CALLS = LLM_DURATION = LLM_TOKENS = LLM_COST = None


def _fold(value: Any, domain: frozenset[str]) -> str:
    return value if isinstance(value, str) and value in domain else "other"


def _safe(fn: Callable[..., None]) -> Callable[..., None]:
    """Wrap a recorder so a metrics failure never perturbs the graph run."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> None:
        if not _METRICS_ON:
            return
        try:
            fn(*args, **kwargs)
        except Exception:  # never raise out of a recorder
            logger.debug("graph metric record failed", exc_info=True)

    return wrapper


# ---------------------------------------------------------------------------
# record_* helpers — the only way instrumentation touches metrics.
# ---------------------------------------------------------------------------
@_safe
def record_run(
    chain_profile: str,
    product_mode: str,
    outcome: str,
    duration_seconds: float | None = None,
) -> None:
    cp = _fold(chain_profile, _CHAIN_PROFILES)
    pm = _fold(product_mode, _PRODUCT_MODES)
    outcome = _fold(outcome, GRAPH_RUN_OUTCOMES)
    GRAPH_RUNS.labels(cp, pm, outcome).inc()
    if outcome == "success" and duration_seconds is not None:
        RUN_DURATION.labels(cp, pm).observe(duration_seconds)


@_safe
def record_node(
    node: str,
    chain_profile: str,
    product_mode: str,
    outcome: str,
    duration_seconds: float | None = None,
) -> None:
    cp = _fold(chain_profile, _CHAIN_PROFILES)
    pm = _fold(product_mode, _PRODUCT_MODES)
    NODE_RUNS.labels(node, cp, pm, outcome).inc()
    if outcome == "success" and duration_seconds is not None:
        NODE_DURATION.labels(node, cp, pm).observe(duration_seconds)


@_safe
def record_llm_call(
    node: str,
    provider: str,
    model: str,
    outcome: str,
    duration_seconds: float | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> None:
    model = model or "unknown"
    LLM_CALLS.labels(node, provider, model, outcome).inc()
    if outcome == "success" and duration_seconds is not None:
        LLM_DURATION.labels(provider, model).observe(duration_seconds)
    if isinstance(prompt_tokens, int) and prompt_tokens > 0:
        LLM_TOKENS.labels(node, provider, model, "prompt").inc(prompt_tokens)
    if isinstance(completion_tokens, int) and completion_tokens > 0:
        LLM_TOKENS.labels(node, provider, model, "completion").inc(completion_tokens)
    cost = cost_usd(model, prompt_tokens, completion_tokens)
    if cost > 0:
        LLM_COST.labels(node, provider, model).inc(cost)


# ---------------------------------------------------------------------------
# Tracing. Shares the OTLP endpoint settings with ops; installs its own provider
# only when the ops one isn't already in place (then graph spans ride it under
# the "app.graph" instrumentation scope).
# ---------------------------------------------------------------------------
_tracer_provider = None


class _NoopSpan:
    def set_attribute(self, *_a: Any, **_k: Any) -> None: ...
    def end(self) -> None: ...
    def __enter__(self): return self
    def __exit__(self, *_a: Any) -> bool: return False


class _NoopTracer:
    def start_as_current_span(self, *_a: Any, **_k: Any) -> "_NoopSpan":
        return _NoopSpan()

    def start_span(self, *_a: Any, **_k: Any) -> "_NoopSpan":
        return _NoopSpan()


def tracing_on() -> bool:
    return _OTEL_AVAILABLE and settings.graph_tracing_active()


def get_tracer():
    """Return an OTel tracer, or a no-op stub when OTel is unavailable."""
    if not _OTEL_AVAILABLE:
        return _NoopTracer()
    return trace.get_tracer("app.graph")


def _sdk_provider_installed() -> bool:
    provider = trace.get_tracer_provider()
    return type(provider).__module__.startswith("opentelemetry.sdk")


def _init_tracing() -> None:
    """Install a TracerProvider unless one (e.g. the ops one) is already installed."""
    global _tracer_provider
    if _tracer_provider is not None or not tracing_on():
        return
    if _sdk_provider_installed():
        return  # ride the ops provider; scope "app.graph" distinguishes graph spans
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

        ratio = max(0.0, min(1.0, settings.otel_traces_sampler_ratio))
        resource = Resource.create({"service.name": settings.graph_otel_service_name})
        provider = TracerProvider(
            resource=resource, sampler=ParentBased(TraceIdRatioBased(ratio))
        )
        endpoint = settings.otel_exporter_otlp_endpoint or ""
        if not endpoint.rstrip("/").endswith("/v1/traces"):
            endpoint = endpoint.rstrip("/") + "/v1/traces"
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        _tracer_provider = provider
        logger.warning("graph tracing enabled endpoint=%s", settings.otel_exporter_otlp_endpoint)
    except Exception:  # never let observability init break startup
        logger.exception("failed to init graph tracing")


def init_graph_observability() -> None:
    """Start exposition/tracing for the graph. Called once, post-fork, in the worker.

    Same ``--concurrency=1`` prefork assumption as the ops exposition: one worker child,
    one registry, one server. When ops metrics are also enabled, ops already bound the
    shared ``:9109`` server (both use the prometheus_client default registry), so this
    only binds when the graph flag is on alone.
    """
    if _METRICS_ON and not (settings.ops_metrics_enabled and _PROM_AVAILABLE):
        try:
            start_http_server(settings.ops_metrics_worker_port)
            logger.warning("graph worker metrics on :%s", settings.ops_metrics_worker_port)
        except Exception:  # pragma: no cover - port already bound / no permission
            logger.exception("failed to start graph metrics server")
    _init_tracing()


# ---------------------------------------------------------------------------
# Wrappers — the three intrusion points (builder nodes, worker run loop, LLM calls).
# ---------------------------------------------------------------------------
def _classify(exc_type: type[BaseException] | None) -> str:
    if exc_type is None:
        return "success"
    if issubclass(exc_type, SessionInterrupted):
        return "interrupted"
    if issubclass(exc_type, (GeneratorExit, asyncio.CancelledError)):
        return "cancelled"
    return "error"


def instrument_node(
    name: str,
    fn: Callable[..., Awaitable[Any]],
    agent: str | None = None,
) -> Callable[..., Awaitable[Any]]:
    """Wrap an async graph node with metrics + a ``graph.node`` span.

    Flags off ⇒ one boolean check, then straight passthrough. Flags on ⇒ sets the
    current-node contextvar (LLM-call attribution), times the node, classifies the
    outcome, and always re-raises.
    """

    @functools.wraps(fn)
    async def wrapper(state: Any) -> Any:
        if not (_METRICS_ON or tracing_on()):
            return await fn(state)

        chain_profile = state.get("chain_profile", "") if hasattr(state, "get") else ""
        product_mode = state.get("product_mode", "") if hasattr(state, "get") else ""
        token = _current_node.set(name)
        started = time.perf_counter()
        outcome = "success"
        try:
            with get_tracer().start_as_current_span("graph.node") as span:
                try:
                    span.set_attribute("graph.node", name)
                    if agent:
                        span.set_attribute("graph.agent", agent)
                    if hasattr(state, "get"):
                        span.set_attribute("graph.session_id", state.get("session_id", ""))
                except Exception:  # attribute failure must not fail the node
                    logger.debug("graph.node span attrs failed", exc_info=True)
                try:
                    return await fn(state)
                except BaseException as exc:
                    outcome = _classify(type(exc))
                    raise
                finally:
                    try:
                        span.set_attribute("graph.outcome", outcome)
                    except Exception:
                        pass
        finally:
            _current_node.reset(token)
            record_node(
                name, chain_profile, product_mode, outcome,
                time.perf_counter() - started,
            )

    return wrapper


class graph_run:
    """Context manager around one full graph run (the worker's ``astream`` loop).

    Opens the root ``graph.run`` span (node spans parent to it via context inheritance)
    and records the run counter + success-only duration. The worker marks the
    between-nodes interrupt early-return via ``set_outcome("interrupted")``. Never
    suppresses exceptions.
    """

    def __init__(self, session_id: str, chain_profile: str, product_mode: str) -> None:
        self._session_id = session_id
        self._chain_profile = chain_profile
        self._product_mode = product_mode
        self._outcome: str | None = None
        self._span_cm = None
        self._span = None
        self._started = 0.0

    def set_outcome(self, outcome: str) -> None:
        self._outcome = outcome

    def set_thread_id(self, thread_id: str) -> None:
        """Span attribute ONLY — thread_id is session-derived (unbounded
        cardinality) and is banned as a metric label."""
        if self._span is not None:
            try:
                self._span.set_attribute("graph.thread_id", thread_id)
            except Exception:
                pass

    def __enter__(self) -> "graph_run":
        if not (_METRICS_ON or tracing_on()):
            return self
        self._started = time.perf_counter()
        try:
            self._span_cm = get_tracer().start_as_current_span("graph.run")
            self._span = self._span_cm.__enter__()
            self._span.set_attribute("graph.session_id", self._session_id)
            self._span.set_attribute("graph.chain_profile", self._chain_profile)
            self._span.set_attribute("graph.product_mode", self._product_mode)
        except Exception:
            logger.debug("graph.run span open failed", exc_info=True)
            self._span_cm = None
            self._span = None
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if not (_METRICS_ON or tracing_on()):
            return False
        outcome = self._outcome if exc_type is None and self._outcome else _classify(exc_type)
        if self._span is not None:
            try:
                self._span.set_attribute("graph.outcome", outcome)
            except Exception:
                pass
        if self._span_cm is not None:
            try:
                self._span_cm.__exit__(exc_type, exc, tb)
            except Exception:
                logger.debug("graph.run span close failed", exc_info=True)
        record_run(
            self._chain_profile, self._product_mode, outcome,
            time.perf_counter() - self._started,
        )
        return False


class llm_call:
    """Context manager around one LLM provider call (``generate`` or ``stream``).

    The provider sets usage as it sees it (``set_usage``); recording happens in
    ``__exit__`` so it also runs at asyncgen finalization: an abandoned stream
    generator receives ``GeneratorExit`` at ``aclose()`` — possibly after the graph
    run has already ended — and still records outcome=cancelled with last-seen usage.

    The span is created un-attached (``start_span``): making it *current* across an
    async generator's yields would attach/detach OTel context in different frames.
    Parenting still resolves from the current context (the ``graph.node`` span) at
    creation time.
    """

    def __init__(self, provider: str, model: str | None, streaming: bool = False) -> None:
        self._provider = provider
        self._model = model or "unknown"
        self._streaming = streaming
        self._prompt_tokens: int | None = None
        self._completion_tokens: int | None = None
        self._span = None
        self._started = 0.0

    def set_usage(self, prompt_tokens: int | None, completion_tokens: int | None) -> None:
        if prompt_tokens is not None:
            self._prompt_tokens = prompt_tokens
        if completion_tokens is not None:
            self._completion_tokens = completion_tokens

    def __enter__(self) -> "llm_call":
        if not (_METRICS_ON or tracing_on()):
            return self
        self._started = time.perf_counter()
        if tracing_on():
            try:
                self._span = get_tracer().start_span("graph.llm")
                self._span.set_attribute("graph.provider", self._provider)
                self._span.set_attribute("graph.model", self._model)
                self._span.set_attribute("graph.streaming", self._streaming)
            except Exception:
                logger.debug("graph.llm span open failed", exc_info=True)
                self._span = None
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if not (_METRICS_ON or tracing_on()):
            return False
        outcome = _classify(exc_type)
        node = _current_node.get()
        if self._span is not None:
            try:
                self._span.set_attribute("graph.outcome", outcome)
                if self._prompt_tokens is not None:
                    self._span.set_attribute("graph.prompt_tokens", self._prompt_tokens)
                if self._completion_tokens is not None:
                    self._span.set_attribute("graph.completion_tokens", self._completion_tokens)
                cost = cost_usd(self._model, self._prompt_tokens, self._completion_tokens)
                if cost > 0:
                    self._span.set_attribute("graph.cost_usd", cost)
                self._span.end()
            except Exception:
                logger.debug("graph.llm span close failed", exc_info=True)
        record_llm_call(
            node, self._provider, self._model, outcome,
            time.perf_counter() - self._started,
            self._prompt_tokens, self._completion_tokens,
        )
        return False
