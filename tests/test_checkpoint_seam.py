"""W3 compile seam, flag, and durability guards (tests 11-16).

Policies under test:
- The bare `compiled_graph` singleton stays eager and checkpointer-free forever
  (the zero-infra eval harness imports it; tests patch it). The checkpointed
  twin is constructed lazily, never at import.
- Flag-on threads thread_id = f"{session_id}:{panel_id}" (per TURN — a
  session-scoped thread makes `fan_in_branches_done` inherit across turns and
  fire the fan-in join early) and durability="sync".
- durability="exit" silently disables the pending-writes mechanism the resume
  guarantee rests on; it is a per-invocation arg a fake-saver unit test cannot
  see, so the worker source is scanned statically (builder-guard idiom,
  tests/test_graph_metrics.py) with a trip test proving the scan has teeth.
"""

from __future__ import annotations

import asyncio
import inspect
import operator
from typing import Annotated, TypedDict
from unittest.mock import MagicMock

import pytest
from langgraph.graph import END, START, StateGraph

import app.graph.builder as builder_module
import app.worker as worker_module
from app.core.config import settings
from app.graph.checkpoint import RedisCheckpointSaver
from tests.checkpoint_fakes import FakeBinaryRedis, FakeBinaryRedisAsync

# --- 11-12. seam shape ---------------------------------------------------------


def test_build_graph_default_has_no_checkpointer() -> None:
    # Flags-off passthrough at the compile level: the module singleton the
    # harness imports is bare.
    assert builder_module.compiled_graph.checkpointer is None
    assert builder_module.build_graph().checkpointer is None


def test_get_checkpointed_graph_lazy_and_cached(monkeypatch) -> None:
    monkeypatch.setattr(builder_module, "_checkpointed_graph", None)
    monkeypatch.setattr(builder_module, "_checkpoint_saver", None)
    assert builder_module.get_checkpoint_saver() is None  # nothing at import

    first = builder_module.get_checkpointed_graph()
    second = builder_module.get_checkpointed_graph()
    assert first is second
    assert first is not builder_module.compiled_graph
    assert isinstance(first.checkpointer, RedisCheckpointSaver)
    assert first.checkpointer is builder_module.get_checkpoint_saver()
    # constructing the twin never mutates the bare singleton
    assert builder_module.compiled_graph.checkpointer is None


# --- 13. worker threading ---------------------------------------------------


def _capturing_graph(calls: dict) -> MagicMock:
    async def fake_astream(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return
        yield  # async generator that yields nothing

    graph = MagicMock()
    graph.astream = fake_astream
    return graph


_STATE = {
    "session_id": "sess-9",
    "panel_id": "panel-7",
    "user_input": "hi",
    "chain_profile": "L4",
    "product_mode": "auto",
}


def test_worker_flag_on_threads_thread_id_and_sync_durability(monkeypatch) -> None:
    calls: dict = {}
    closes: list[bool] = []

    class _StubSaver:
        async def aclose(self) -> None:
            closes.append(True)

    monkeypatch.setattr(settings, "graph_checkpointing_enabled", True)
    monkeypatch.setattr(
        worker_module, "get_checkpointed_graph", lambda: _capturing_graph(calls)
    )
    monkeypatch.setattr(worker_module, "get_checkpoint_saver", lambda: _StubSaver())

    asyncio.run(
        worker_module._run_graph_with_streaming(
            dict(_STATE), MagicMock(), "channel_sess-9", "sess-9"
        )
    )
    state_arg, config_arg = calls["args"]
    assert state_arg["panel_id"] == "panel-7"
    assert config_arg == {"configurable": {"thread_id": "sess-9:panel-7"}}
    assert calls["kwargs"] == {"stream_mode": "updates", "durability": "sync"}
    assert closes == [True], "saver.aclose() must run after the stream is closed"


def test_worker_flag_off_uses_bare_graph_no_config(monkeypatch) -> None:
    calls: dict = {}
    monkeypatch.setattr(worker_module, "compiled_graph", _capturing_graph(calls))
    asyncio.run(
        worker_module._run_graph_with_streaming(
            dict(_STATE), MagicMock(), "channel_sess-9", "sess-9"
        )
    )
    (state_arg,) = calls["args"]
    assert state_arg["panel_id"] == "panel-7"
    assert calls["kwargs"] == {"stream_mode": "updates"}


def test_worker_empty_session_never_checkpoints(monkeypatch) -> None:
    # The eval harness runs with session_id="" — flag-on must not change it.
    calls: dict = {}
    monkeypatch.setattr(settings, "graph_checkpointing_enabled", True)
    monkeypatch.setattr(worker_module, "compiled_graph", _capturing_graph(calls))
    state = dict(_STATE, session_id="")
    asyncio.run(
        worker_module._run_graph_with_streaming(state, MagicMock(), "channel_", "")
    )
    assert calls["kwargs"] == {"stream_mode": "updates"}


# --- 14-15. static durability guard -------------------------------------------


def _assert_no_exit_durability(source: str) -> None:
    for banned in (
        'durability="exit"',
        "durability='exit'",
        "checkpoint_during",  # deprecated alias: checkpoint_during=False IS "exit"
    ):
        assert banned not in source, f"forbidden durability spelling: {banned!r}"


def test_worker_astream_never_exit_durability() -> None:
    source = inspect.getsource(worker_module)
    astream_lines = [ln for ln in source.splitlines() if ".astream(" in ln]
    # flag-on + flag-off call sites — if this shrinks, the scan went vacuous.
    assert len(astream_lines) >= 2, (
        f"expected >=2 astream sites in app/worker.py, found {len(astream_lines)}"
    )
    assert 'durability="sync"' in source, "flag-on astream must pin durability=sync"
    _assert_no_exit_durability(source)


def test_durability_guard_trips_on_synthetic_violation() -> None:
    planted = 'stream = graph.astream(state, config, durability="exit")'
    with pytest.raises(AssertionError):
        _assert_no_exit_durability(planted)


# --- 16. thread-per-turn state leak ---------------------------------------------


class _LeakState(TypedDict):
    done: Annotated[list[str], operator.add]


def _mini_graph(checkpointer) -> object:
    builder = StateGraph(_LeakState)
    builder.add_node("mark", lambda state: {"done": ["ran"]})
    builder.add_edge(START, "mark")
    builder.add_edge("mark", END)
    return builder.compile(checkpointer=checkpointer)


def test_thread_per_turn_no_state_leak(monkeypatch) -> None:
    store = FakeBinaryRedis()
    monkeypatch.setattr(
        "app.graph.checkpoint.create_binary_sync_redis", lambda: store
    )
    monkeypatch.setattr(
        "app.graph.checkpoint.create_binary_async_redis",
        lambda: FakeBinaryRedisAsync(store),
    )
    graph = _mini_graph(RedisCheckpointSaver(ttl_seconds=60))

    def run_turn(thread_id: str) -> dict:
        return asyncio.run(
            graph.ainvoke(
                {"done": []},
                {"configurable": {"thread_id": thread_id}},
                durability="sync",
            )
        )

    # Per-turn threads: each turn starts clean.
    assert run_turn("sess:turn-1")["done"] == ["ran"]
    assert run_turn("sess:turn-2")["done"] == ["ran"]

    # Control leg — SAME thread id across turns: the operator.add channel
    # inherits turn 1's entry. This is exactly the fan_in_branches_done
    # inheritance that fires the fan-in join early with thread_id=session_id,
    # and why thread_id = f"{session_id}:{panel_id}" is per turn.
    assert run_turn("sess:turn-1")["done"] == ["ran", "ran"]
