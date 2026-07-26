"""Cardinality-discipline + safety guards for product-graph observability (W2).

Twin of ``tests/test_ops_metrics.py``: turns the "metric labels must be bounded" rule
into a permanent CI tripwire for the ``tess_graph_`` plane, and asserts the ``record_*``
helpers and wrappers never raise (a metrics failure must never perturb a graph run).

One improvement over the ops twin: the allowlist check is factored into
``_assert_labels_ok`` and a trip test proves the guard itself has teeth — a throwaway
banned-label metric must fail it. (Follow-up filed in docs/W2_OPENER.md: port the trip
test to the ops twin in a later ops-path session.)

Label-domain rules: ``provider`` is banned in ops-land (shadows unbounded multi-cloud
provider records) but admitted here strictly as the bounded ``LLMProvider`` enum;
``model`` values come only from config (``settings.ollama_model`` / ``gemini_model`` /
``LLMConfig.model``); unknown ``chain_profile`` / ``product_mode`` fold to ``"other"``.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.session_control import SessionInterrupted
from app.graph import observability as obs
from app.graph.model_costs import cost_usd

pytestmark = pytest.mark.skipif(
    not obs._PROM_AVAILABLE, reason="prometheus_client not installed"
)

# The ONLY label names any graph metric may use. Every value is a fixed code enum,
# config-bounded, or folds to "other". Adding a new label requires adding it here on
# purpose.
ALLOWED_LABELS = {
    "node", "chain_profile", "product_mode", "outcome", "provider", "model", "kind",
}

# Anything that is (or can become) unbounded — banned as a metric label forever.
# (Fine as span attributes, which are not aggregated; never as metric labels.)
BANNED_LABELS = {
    "session_id", "panel_id", "url", "path", "error", "last_error", "message",
    "trace_id", "request_id", "user_input", "agent_id", "provider_id",
}


@pytest.fixture(autouse=True)
def _tracing_off(monkeypatch: pytest.MonkeyPatch):
    """Pin graph tracing off so wrapper tests exercise the metrics path only."""
    monkeypatch.setattr(obs.settings, "graph_tracing_enabled", False)


def _assert_labels_ok(metric) -> None:
    for label in metric._labelnames:
        assert label in ALLOWED_LABELS, f"{metric._name}: unexpected label {label!r}"
        assert label not in BANNED_LABELS, f"{metric._name}: BANNED label {label!r}"


def _sample(metric, suffix: str, labels: dict[str, str]) -> float:
    """Sum matching sample values; 0.0 when no sample matches."""
    total = 0.0
    for family in metric.collect():
        for s in family.samples:
            if s.name.endswith(suffix) and all(
                s.labels.get(k) == v for k, v in labels.items()
            ):
                total += s.value
    return total


# ---------------------------------------------------------------------------
# Cardinality guards.
# ---------------------------------------------------------------------------
def test_all_metrics_are_tess_graph_prefixed():
    assert obs.ALL_GRAPH_METRICS, "no graph metrics registered"
    for m in obs.ALL_GRAPH_METRICS:
        assert m._name.startswith("tess_graph_"), m._name


def test_every_label_is_allowlisted_and_not_banned():
    for m in obs.ALL_GRAPH_METRICS:
        _assert_labels_ok(m)


def test_no_metric_uses_session_id():
    # The unbounded-id footgun this guard exists to prevent.
    for m in obs.ALL_GRAPH_METRICS:
        assert "session_id" not in m._labelnames, m._name


def test_label_guard_trips_on_banned_label():
    """Non-vacuity: the guard itself must have teeth, permanently."""
    from prometheus_client import CollectorRegistry, Counter

    bad = Counter(
        "tess_graph_trip_example",
        "throwaway banned-label metric for the guard trip test",
        ["session_id"],
        registry=CollectorRegistry(),
    )
    with pytest.raises(AssertionError):
        _assert_labels_ok(bad)


def test_provider_label_domain_is_the_llm_provider_enum():
    from app.llm.base import LLMProvider

    assert {p.value for p in LLMProvider} == {"gemini", "ollama"}


def test_fold_domains_match_the_registries():
    from app.core.chain_profiles import ChainProfile
    from app.core.product_modes import ProductMode

    assert obs._CHAIN_PROFILES == {p.value for p in ChainProfile}
    assert obs._PRODUCT_MODES == {m.value for m in ProductMode}


# ---------------------------------------------------------------------------
# record_* never raise; garbage inputs degrade, never explode.
# ---------------------------------------------------------------------------
def _exercise_all_recorders() -> None:
    obs.record_run("L4", "auto", "success", 1.2)
    obs.record_run("weird", None, "error", None)  # type: ignore[arg-type]
    obs.record_node("presenter", "L0", "auto", "success", 0.4)
    obs.record_node("presenter", "nope", "nope", "interrupted", -1.0)
    obs.record_llm_call("presenter", "ollama", "llama3.2", "success", 0.2, 10, 5)
    obs.record_llm_call("unknown", "gemini", None, "error", None, -3, None)


def test_recorders_never_raise_when_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(obs, "_METRICS_ON", False)
    _exercise_all_recorders()  # must not raise


def test_recorders_never_raise_when_enabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(obs, "_METRICS_ON", True)
    _exercise_all_recorders()  # must not raise


def test_unknown_chain_profile_and_mode_fold_to_other(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(obs, "_METRICS_ON", True)
    before = _sample(
        obs.NODE_RUNS, "_total",
        {"node": "fold_probe", "chain_profile": "other", "product_mode": "other"},
    )
    obs.record_node("fold_probe", "L99", "gibberish", "success", 0.1)
    after = _sample(
        obs.NODE_RUNS, "_total",
        {"node": "fold_probe", "chain_profile": "other", "product_mode": "other"},
    )
    assert after == before + 1


def test_duration_histograms_record_success_only(monkeypatch: pytest.MonkeyPatch):
    """Sign-off policy: interrupted runs advance the counter, never the histogram —
    short interrupted runs must not pollute latency trends in the flattering direction."""
    monkeypatch.setattr(obs, "_METRICS_ON", True)
    hist_labels = {"node": "policy_probe", "chain_profile": "L4", "product_mode": "auto"}
    hist_before = _sample(obs.NODE_DURATION, "_count", hist_labels)
    count_before = _sample(obs.NODE_RUNS, "_total", {**hist_labels, "outcome": "interrupted"})

    obs.record_node("policy_probe", "L4", "auto", "interrupted", 0.01)
    assert _sample(obs.NODE_RUNS, "_total", {**hist_labels, "outcome": "interrupted"}) == count_before + 1
    assert _sample(obs.NODE_DURATION, "_count", hist_labels) == hist_before

    obs.record_node("policy_probe", "L4", "auto", "success", 0.01)
    assert _sample(obs.NODE_DURATION, "_count", hist_labels) == hist_before + 1


def test_run_duration_success_only(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(obs, "_METRICS_ON", True)
    labels = {"chain_profile": "L1", "product_mode": "coding"}
    before = _sample(obs.RUN_DURATION, "_count", labels)
    obs.record_run("L1", "coding", "error", 5.0)
    assert _sample(obs.RUN_DURATION, "_count", labels) == before
    obs.record_run("L1", "coding", "success", 5.0)
    assert _sample(obs.RUN_DURATION, "_count", labels) == before + 1


# ---------------------------------------------------------------------------
# instrument_node wrapper.
# ---------------------------------------------------------------------------
_STATE = {"chain_profile": "L4", "product_mode": "auto", "session_id": "s-test", "x": 1}


def test_instrument_node_flags_off_is_passthrough(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(obs, "_METRICS_ON", False)

    async def node(state):
        assert obs._current_node.get() == "unknown"  # contextvar untouched when off
        return {"x": state["x"] + 1}

    wrapped = obs.instrument_node("off_probe", node)
    assert asyncio.run(wrapped(dict(_STATE))) == {"x": 2}
    assert obs._current_node.get() == "unknown"


def test_instrument_node_records_success_and_sets_contextvar(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(obs, "_METRICS_ON", True)
    seen: list[str] = []

    async def node(state):
        seen.append(obs._current_node.get())
        return {"ok": True}

    wrapped = obs.instrument_node("ctx_probe", node)
    labels = {"node": "ctx_probe", "chain_profile": "L4", "product_mode": "auto"}
    runs_before = _sample(obs.NODE_RUNS, "_total", {**labels, "outcome": "success"})
    dur_before = _sample(obs.NODE_DURATION, "_count", labels)

    assert asyncio.run(wrapped(dict(_STATE))) == {"ok": True}
    assert seen == ["ctx_probe"]
    assert obs._current_node.get() == "unknown"  # reset after the call
    assert _sample(obs.NODE_RUNS, "_total", {**labels, "outcome": "success"}) == runs_before + 1
    assert _sample(obs.NODE_DURATION, "_count", labels) == dur_before + 1


def test_instrument_node_interrupted_reraises_no_histogram(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(obs, "_METRICS_ON", True)

    async def node(state):
        raise SessionInterrupted()

    wrapped = obs.instrument_node("int_probe", node)
    labels = {"node": "int_probe", "chain_profile": "L4", "product_mode": "auto"}
    dur_before = _sample(obs.NODE_DURATION, "_count", labels)
    runs_before = _sample(obs.NODE_RUNS, "_total", {**labels, "outcome": "interrupted"})

    with pytest.raises(SessionInterrupted):
        asyncio.run(wrapped(dict(_STATE)))
    assert _sample(obs.NODE_RUNS, "_total", {**labels, "outcome": "interrupted"}) == runs_before + 1
    assert _sample(obs.NODE_DURATION, "_count", labels) == dur_before


def test_instrument_node_error_reraises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(obs, "_METRICS_ON", True)

    async def node(state):
        raise ValueError("boom")

    wrapped = obs.instrument_node("err_probe", node)
    before = _sample(
        obs.NODE_RUNS, "_total",
        {"node": "err_probe", "chain_profile": "L4", "product_mode": "auto", "outcome": "error"},
    )
    with pytest.raises(ValueError):
        asyncio.run(wrapped(dict(_STATE)))
    after = _sample(
        obs.NODE_RUNS, "_total",
        {"node": "err_probe", "chain_profile": "L4", "product_mode": "auto", "outcome": "error"},
    )
    assert after == before + 1


# ---------------------------------------------------------------------------
# graph_run wrapper.
# ---------------------------------------------------------------------------
def test_graph_run_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(obs, "_METRICS_ON", True)
    labels = {"chain_profile": "L2", "product_mode": "research"}
    runs_before = _sample(obs.GRAPH_RUNS, "_total", {**labels, "outcome": "success"})
    dur_before = _sample(obs.RUN_DURATION, "_count", labels)

    with obs.graph_run("s-run", "L2", "research"):
        pass
    assert _sample(obs.GRAPH_RUNS, "_total", {**labels, "outcome": "success"}) == runs_before + 1
    assert _sample(obs.RUN_DURATION, "_count", labels) == dur_before + 1


def test_graph_run_interrupted_early_return(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(obs, "_METRICS_ON", True)
    labels = {"chain_profile": "L3", "product_mode": "planner"}
    dur_before = _sample(obs.RUN_DURATION, "_count", labels)

    with obs.graph_run("s-run", "L3", "planner") as run:
        run.set_outcome("interrupted")
    assert _sample(obs.GRAPH_RUNS, "_total", {**labels, "outcome": "interrupted"}) >= 1
    assert _sample(obs.RUN_DURATION, "_count", labels) == dur_before  # success-only


def test_graph_run_exception_classified_and_propagated(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(obs, "_METRICS_ON", True)
    labels = {"chain_profile": "L4", "product_mode": "builder"}
    before = _sample(obs.GRAPH_RUNS, "_total", {**labels, "outcome": "error"})
    with pytest.raises(RuntimeError):
        with obs.graph_run("s-run", "L4", "builder"):
            raise RuntimeError("boom")
    assert _sample(obs.GRAPH_RUNS, "_total", {**labels, "outcome": "error"}) == before + 1


# ---------------------------------------------------------------------------
# llm_call wrapper.
# ---------------------------------------------------------------------------
def test_llm_call_success_records_usage(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(obs, "_METRICS_ON", True)
    token = obs._current_node.set("llm_probe")
    try:
        labels = {"node": "llm_probe", "provider": "ollama", "model": "llama3.2"}
        calls_before = _sample(obs.LLM_CALLS, "_total", {**labels, "outcome": "success"})
        pt_before = _sample(obs.LLM_TOKENS, "_total", {**labels, "kind": "prompt"})

        with obs.llm_call("ollama", "llama3.2") as rec:
            rec.set_usage(10, 5)

        assert _sample(obs.LLM_CALLS, "_total", {**labels, "outcome": "success"}) == calls_before + 1
        assert _sample(obs.LLM_TOKENS, "_total", {**labels, "kind": "prompt"}) == pt_before + 10
        assert _sample(obs.LLM_TOKENS, "_total", {**labels, "kind": "completion"}) >= 5
        # local model → no cost series
        assert _sample(obs.LLM_COST, "_total", labels) == 0.0
    finally:
        obs._current_node.reset(token)


def test_llm_call_cancelled_at_generator_close_records_last_usage(
    monkeypatch: pytest.MonkeyPatch,
):
    """The consumer abandons the stream; recording happens at asyncgen finalization.

    The test closes the generator explicitly — finalization is GC-driven otherwise
    and the assert would race.
    """
    monkeypatch.setattr(obs, "_METRICS_ON", True)
    token = obs._current_node.set("cancel_probe")
    try:
        labels = {"node": "cancel_probe", "provider": "ollama", "model": "llama3.2"}
        cancelled_before = _sample(obs.LLM_CALLS, "_total", {**labels, "outcome": "cancelled"})
        pt_before = _sample(obs.LLM_TOKENS, "_total", {**labels, "kind": "prompt"})
        dur_before = _sample(obs.LLM_DURATION, "_count", {"provider": "ollama", "model": "llama3.2"})

        async def fake_stream():
            with obs.llm_call("ollama", "llama3.2", streaming=True) as rec:
                rec.set_usage(7, None)
                yield "a"
                yield "b"

        async def drive():
            agen = fake_stream()
            assert await agen.__anext__() == "a"
            await agen.aclose()  # GeneratorExit at the yield → llm_call.__exit__

        asyncio.run(drive())
        assert _sample(obs.LLM_CALLS, "_total", {**labels, "outcome": "cancelled"}) == cancelled_before + 1
        assert _sample(obs.LLM_TOKENS, "_total", {**labels, "kind": "prompt"}) == pt_before + 7
        # cancelled → success-only duration histogram unchanged
        assert _sample(obs.LLM_DURATION, "_count", {"provider": "ollama", "model": "llama3.2"}) == dur_before
    finally:
        obs._current_node.reset(token)


def test_llm_call_cost_recorded_for_priced_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(obs, "_METRICS_ON", True)
    token = obs._current_node.set("cost_probe")
    try:
        labels = {"node": "cost_probe", "provider": "gemini", "model": "gemini-2.0-flash"}
        before = _sample(obs.LLM_COST, "_total", labels)
        with obs.llm_call("gemini", "gemini-2.0-flash") as rec:
            rec.set_usage(1_000_000, 0)
        after = _sample(obs.LLM_COST, "_total", labels)
        assert after - before == pytest.approx(0.10)
    finally:
        obs._current_node.reset(token)


# ---------------------------------------------------------------------------
# Cost map.
# ---------------------------------------------------------------------------
def test_cost_known_model_math():
    assert cost_usd("gemini-2.0-flash", 1_000_000, 1_000_000) == pytest.approx(0.50)


def test_cost_prefix_match_longest_wins():
    assert cost_usd("gemini-2.0-flash-001", 1_000_000, 0) == pytest.approx(0.10)
    # -lite must match the lite price, not the shorter "gemini-2.0-flash" prefix
    assert cost_usd("gemini-2.0-flash-lite-001", 1_000_000, 0) == pytest.approx(0.075)


def test_cost_unknown_and_local_models_are_zero():
    assert cost_usd("llama3.2", 1_000_000, 1_000_000) == 0.0
    assert cost_usd(None, 100, 100) == 0.0
    assert cost_usd("", 100, 100) == 0.0


def test_cost_garbage_token_counts_are_zero():
    assert cost_usd("gemini-2.0-flash", None, None) == 0.0
    assert cost_usd("gemini-2.0-flash", -5, -5) == 0.0
