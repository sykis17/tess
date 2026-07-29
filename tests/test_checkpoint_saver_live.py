"""Live-Redis leg of the checkpointer contract + resume battery (P1 Step 5).

House parity pattern (tests/test_fence_store_parity.py): the SAME shared
assertion bodies as the fake-backed suites — ``_assert_checkpointer_contract``
from tests/test_checkpoint_saver.py, and the resume/replay battery shapes from
tests/test_checkpoint_resume.py — run here against a REAL Redis through the
real binary factories (app/core/redis.py). Never ``decode_responses=True``:
the serializer emits msgpack bytes and a decoding client corrupts silently.

Skips without ``OPS_TEST_REDIS_URL``; the redis-parity CI job asserts from the
junit artifact that nothing skipped (vacuity guard). Point the URL at a
DISPOSABLE database — every test flushes it first::

    OPS_TEST_REDIS_URL=redis://127.0.0.1:6379/9 pytest tests/test_checkpoint_saver_live.py

The no-checkpointer red leg (test 18) stays fake-only: it proves a framework
property that needs no Redis at all.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from langgraph.graph import END, START, StateGraph

from app.core.config import settings
from app.core.redis import create_binary_sync_redis
from app.graph.checkpoint import RedisCheckpointSaver
from tests.test_checkpoint_resume import _consume, _fan_graph, _LinState
from tests.test_checkpoint_saver import (
    TTL,
    _assert_checkpointer_contract,
    _mk_checkpoint,
    _thread_cfg,
)


def _test_redis_url() -> str | None:
    return (os.environ.get("OPS_TEST_REDIS_URL") or "").strip() or None


_REDIS_URL = _test_redis_url()

pytestmark = pytest.mark.skipif(
    _REDIS_URL is None,
    reason="OPS_TEST_REDIS_URL not set (live-Redis checkpointer leg)",
)


@pytest.fixture()
def live_redis(monkeypatch):
    """Route the real binary factories at the test endpoint and start clean.

    settings.redis_url is the factories' single input, so patching it means the
    saver exercises the exact production construction path (from_url,
    decode_responses=False) — no client stand-ins anywhere.
    """
    monkeypatch.setattr(settings, "redis_url", _REDIS_URL)
    client = create_binary_sync_redis()
    client.flushdb()  # disposable-DB doctrine: see module docstring
    yield client
    client.close()


@pytest.fixture()
def saver(live_redis) -> RedisCheckpointSaver:
    return RedisCheckpointSaver(ttl_seconds=TTL)


# --- 1. the shared contract body, live -----------------------------------------


def test_checkpointer_contract_live(saver) -> None:
    _assert_checkpointer_contract(saver)


# --- 2. TTL lands on the real wire ----------------------------------------------


def test_ttl_applied_to_every_key_live(saver, live_redis) -> None:
    cfg = saver.put(
        _thread_cfg("ttl-live"), _mk_checkpoint("1"), {"source": "loop", "step": 0}, {}
    )
    saver.put_writes(cfg, [("collected_data", ["x"])], task_id="t1")
    keys = list(live_redis.scan_iter(match=b"graph:ckpt*"))
    assert keys, "no checkpoint keys created"
    for key in keys:
        ttl = live_redis.ttl(key)
        assert 0 < ttl <= TTL, f"missing/wrong TTL on {key!r}: {ttl}"


# --- 3-4. resume battery over the real Pregel loop + real Redis -----------------
# Mirrors tests 17 and 22 of tests/test_checkpoint_resume.py through the same
# binary-factory seam; the saver's loop-stamped async client handles the fresh
# event loop per asyncio.run.


def _done_write_recorded_live(client):
    def _visible() -> bool:
        for key in client.scan_iter(match=b"graph:ckpt-writes:*"):
            for value in client.hgetall(key).values():
                if b"done" in value:
                    return True
        return False

    return _visible


def test_resume_after_interrupt_no_double_execution_live(saver, live_redis) -> None:
    counters = {"a": 0, "b": 0}
    graph = _fan_graph(
        saver,
        counters,
        {"armed": True},
        _done_write_recorded_live(live_redis),
    )
    cfg = {"configurable": {"thread_id": "live:panel-1"}}

    with pytest.raises(RuntimeError, match="controlled mid-fan-out abort"):
        asyncio.run(
            _consume(
                graph.astream(
                    {"done": []}, cfg, stream_mode="updates", durability="sync"
                )
            )
        )
    assert counters == {"a": 1, "b": 0}, "branch_a must complete before the abort"

    nodes = asyncio.run(
        _consume(graph.astream(None, cfg, stream_mode="updates", durability="sync"))
    )
    assert counters == {"a": 1, "b": 1}, "branch_a double-executed on resume"
    assert "branch_b" in nodes

    async def _final_state():
        state = await graph.aget_state(cfg)
        await saver.aclose()
        return state

    final = asyncio.run(_final_state())
    assert sorted(final.values["done"]) == ["a", "b"], "continuation incoherent"


def test_replay_reproduces_node_sequence_live(saver) -> None:
    # _LinState must be a module-level TypedDict (imported from the fake-backed
    # suite): LangGraph resolves its Annotated reducers via module globals.
    builder = StateGraph(_LinState)
    builder.add_node("n1", lambda s: {"seen": ["n1"]})
    builder.add_node("n2", lambda s: {"seen": ["n2"]})
    builder.add_edge(START, "n1")
    builder.add_edge("n1", "n2")
    builder.add_edge("n2", END)
    graph = builder.compile(checkpointer=saver)
    cfg = {"configurable": {"thread_id": "live-replay:1"}}

    original = asyncio.run(
        _consume(
            graph.astream({"seen": []}, cfg, stream_mode="updates", durability="sync")
        )
    )
    assert original == ["n1", "n2"]

    tuples = list(saver.list(cfg))
    steps = [t.metadata.get("step") for t in tuples]
    assert steps == sorted(steps, reverse=True)
    root = tuples[-1]
    assert root.metadata.get("source") == "input"

    replay_cfg = {
        "configurable": {
            "thread_id": "live-replay:1",
            "checkpoint_id": root.checkpoint["id"],
        }
    }

    async def _replay():
        replayed = await _consume(
            graph.astream(None, replay_cfg, stream_mode="updates", durability="sync")
        )
        await saver.aclose()
        return replayed

    assert asyncio.run(_replay()) == original
