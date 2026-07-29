"""Token-usage extraction + provider recording tests (W2 commit 4).

No live LLM, no pytest-asyncio: fake LangChain models drive the real provider
``generate``/``stream`` methods via ``asyncio.run`` (the suite convention). Providers
are built with ``__new__`` + direct attributes so no constructor touches network or
needs credentials.
"""

from __future__ import annotations

import asyncio

import pytest

from app.graph import observability as obs
from app.llm.gemini import GeminiLLM
from app.llm.ollama import OllamaLLM
from app.llm.types import LLMMessage, LLMRequest, LLMResponse
from app.llm.usage import extract_usage

pytestmark = pytest.mark.skipif(
    not obs._PROM_AVAILABLE, reason="prometheus_client not installed"
)


class _Msg:
    """Message/chunk fake: only the attributes extract_usage and the providers read."""

    def __init__(self, content="", usage_metadata=None, response_metadata=None):
        self.content = content
        if usage_metadata is not None:
            self.usage_metadata = usage_metadata
        self.response_metadata = response_metadata or {}


class _FakeModel:
    def __init__(self, result=None, chunks=None):
        self._result = result
        self._chunks = chunks or []

    async def ainvoke(self, messages):
        return self._result

    async def astream(self, messages):
        for chunk in self._chunks:
            yield chunk


def _ollama(model_name: str, fake: _FakeModel) -> OllamaLLM:
    llm = OllamaLLM.__new__(OllamaLLM)
    llm._model_name = model_name
    llm._model = fake
    return llm


def _gemini(model_name: str, fake: _FakeModel) -> GeminiLLM:
    llm = GeminiLLM.__new__(GeminiLLM)
    llm._model_name = model_name
    llm._model = fake
    return llm


def _request() -> LLMRequest:
    return LLMRequest(messages=[LLMMessage(role="user", content="hi")])


def _sample(metric, suffix: str, labels: dict[str, str]) -> float:
    total = 0.0
    for family in metric.collect():
        for s in family.samples:
            if s.name.endswith(suffix) and all(
                s.labels.get(k) == v for k, v in labels.items()
            ):
                total += s.value
    return total


@pytest.fixture(autouse=True)
def _tracing_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(obs.settings, "graph_tracing_enabled", False)


# ---------------------------------------------------------------------------
# extract_usage.
# ---------------------------------------------------------------------------
def test_extract_from_usage_metadata():
    msg = _Msg(usage_metadata={"input_tokens": 10, "output_tokens": 5})
    assert extract_usage(msg) == (10, 5)


def test_extract_prefers_usage_metadata_over_response_metadata():
    msg = _Msg(
        usage_metadata={"input_tokens": 10, "output_tokens": 5},
        response_metadata={"prompt_eval_count": 99, "eval_count": 99},
    )
    assert extract_usage(msg) == (10, 5)


def test_extract_ollama_response_metadata_fallback():
    msg = _Msg(response_metadata={"prompt_eval_count": 12, "eval_count": 34})
    assert extract_usage(msg) == (12, 34)


def test_extract_garbage_returns_none():
    assert extract_usage(object()) == (None, None)
    assert extract_usage(_Msg()) == (None, None)
    assert extract_usage(_Msg(usage_metadata={"input_tokens": "x", "output_tokens": "y"})) == (None, None)
    assert extract_usage(None) == (None, None)


def test_llmresponse_token_fields_default_none():
    resp = LLMResponse(content="c", provider="ollama", model="m")
    assert resp.prompt_tokens is None
    assert resp.completion_tokens is None


# ---------------------------------------------------------------------------
# Provider plumbing: generate.
# ---------------------------------------------------------------------------
def test_ollama_generate_populates_tokens_and_records(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(obs, "_METRICS_ON", True)
    llm = _ollama(
        "fake-oll-gen",
        _FakeModel(result=_Msg("hello", usage_metadata={"input_tokens": 11, "output_tokens": 3})),
    )
    labels = {"node": "unknown", "provider": "ollama", "model": "fake-oll-gen"}
    pt_before = _sample(obs.LLM_TOKENS, "_total", {**labels, "kind": "prompt"})
    calls_before = _sample(obs.LLM_CALLS, "_total", {**labels, "outcome": "success"})

    resp = asyncio.run(llm.generate(_request()))

    assert resp.content == "hello"
    assert resp.prompt_tokens == 11
    assert resp.completion_tokens == 3
    # the provider-side record call is load-bearing: delete it and this goes red
    assert _sample(obs.LLM_TOKENS, "_total", {**labels, "kind": "prompt"}) == pt_before + 11
    assert _sample(obs.LLM_CALLS, "_total", {**labels, "outcome": "success"}) == calls_before + 1


def test_gemini_generate_populates_tokens_and_records(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(obs, "_METRICS_ON", True)
    llm = _gemini(
        "fake-gem-gen",
        _FakeModel(result=_Msg("hi", usage_metadata={"input_tokens": 7, "output_tokens": 2})),
    )
    labels = {"node": "unknown", "provider": "gemini", "model": "fake-gem-gen"}
    ct_before = _sample(obs.LLM_TOKENS, "_total", {**labels, "kind": "completion"})

    resp = asyncio.run(llm.generate(_request()))

    assert (resp.prompt_tokens, resp.completion_tokens) == (7, 2)
    assert _sample(obs.LLM_TOKENS, "_total", {**labels, "kind": "completion"}) == ct_before + 2


def test_generate_without_usage_degrades_to_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(obs, "_METRICS_ON", True)
    llm = _ollama("fake-oll-nousage", _FakeModel(result=_Msg("plain")))
    resp = asyncio.run(llm.generate(_request()))
    assert resp.content == "plain"
    assert resp.prompt_tokens is None
    assert resp.completion_tokens is None


# ---------------------------------------------------------------------------
# Provider plumbing: stream.
# ---------------------------------------------------------------------------
def test_ollama_stream_yields_content_and_records_final_usage(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(obs, "_METRICS_ON", True)
    # Final done chunk: usage-bearing, empty content — never yielded, but seen.
    llm = _ollama(
        "fake-oll-stream",
        _FakeModel(chunks=[
            _Msg("a"),
            _Msg("b"),
            _Msg("", usage_metadata={"input_tokens": 21, "output_tokens": 8}),
        ]),
    )
    labels = {"node": "unknown", "provider": "ollama", "model": "fake-oll-stream"}
    pt_before = _sample(obs.LLM_TOKENS, "_total", {**labels, "kind": "prompt"})

    async def drive() -> list[str]:
        return [chunk async for chunk in llm.stream(_request())]

    assert asyncio.run(drive()) == ["a", "b"]
    assert _sample(obs.LLM_TOKENS, "_total", {**labels, "kind": "prompt"}) == pt_before + 21
    assert _sample(obs.LLM_CALLS, "_total", {**labels, "outcome": "success"}) >= 1


def test_ollama_stream_abandoned_records_cancelled_with_last_usage(
    monkeypatch: pytest.MonkeyPatch,
):
    """Consumer walks away mid-stream; explicit aclose() makes finalization
    deterministic (GC-driven otherwise) — llm_call records cancelled + last usage."""
    monkeypatch.setattr(obs, "_METRICS_ON", True)
    llm = _ollama(
        "fake-oll-cancel",
        _FakeModel(chunks=[
            _Msg("a", response_metadata={"prompt_eval_count": 4, "eval_count": 1}),
            _Msg("b"),
        ]),
    )
    labels = {"node": "unknown", "provider": "ollama", "model": "fake-oll-cancel"}
    cancelled_before = _sample(obs.LLM_CALLS, "_total", {**labels, "outcome": "cancelled"})

    async def drive() -> None:
        agen = llm.stream(_request())
        assert await agen.__anext__() == "a"
        await agen.aclose()

    asyncio.run(drive())
    assert _sample(obs.LLM_CALLS, "_total", {**labels, "outcome": "cancelled"}) == cancelled_before + 1
    assert _sample(obs.LLM_TOKENS, "_total", {**labels, "kind": "prompt"}) >= 4


# ---------------------------------------------------------------------------
# W3 regression: the Ollama serialization lock must survive event-loop
# turnover. Every Celery task runs its own loop (asyncio.run); an asyncio.Lock
# binds to the loop that first CONTENDS it (the uncontended acquire fast path
# never binds — which is why single-call tests stay green), so a module-level
# lock breaks the SECOND task on the same prefork child with "is bound to a
# different event loop": any turn 2, and every resume. Found live by the W3
# flag-on resume smoke.
# ---------------------------------------------------------------------------
class _YieldingModel(_FakeModel):
    """Holds the lock across a scheduler tick so a sibling call really contends."""

    async def ainvoke(self, messages):
        await asyncio.sleep(0)
        return self._result


def test_ollama_lock_survives_event_loop_turnover():
    async def contended(llm: OllamaLLM) -> None:
        await asyncio.gather(llm.generate(_request()), llm.generate(_request()))

    # Loop A: contention binds whatever lock the provider uses to loop A.
    asyncio.run(contended(_ollama("fake-oll-loop", _YieldingModel(result=_Msg("x")))))
    # Loop B (the Celery task boundary): contended acquire again. Red with a
    # module-level lock (RuntimeError: ... bound to a different event loop).
    asyncio.run(contended(_ollama("fake-oll-loop", _YieldingModel(result=_Msg("y")))))
