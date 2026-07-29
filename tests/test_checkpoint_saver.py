"""Contract battery for the W3 RedisCheckpointSaver (fake-backed).

House parity pattern (tests/test_fence_store_parity.py): the shared assertion
body `_assert_checkpointer_contract` is the anchor — the live-Redis CI leg
(tests/test_checkpoint_saver_live.py, the per-push `redis-parity` job) runs the
same body plus the resume battery against a real binary client. Its 4 tests
skip without OPS_TEST_REDIS_URL: per-push CI pins the suite-wide skip tally at
exactly 6 (2 etcd parity + 4 redis-live).

Policy under test (never-silent doctrine): the framework serializer degrades a
failed pydantic reconstruction to a raw kwargs dict WITHOUT raising; the saver's
post-load validation must turn that into a loud CheckpointDeserializationError.
"""

from __future__ import annotations

import asyncio
import copy

import pytest
from langgraph.checkpoint.base import WRITES_IDX_MAP

from app.graph.checkpoint import (
    _CHANNEL_MODEL_TYPES,
    CheckpointDeserializationError,
    RedisCheckpointSaver,
)
from app.graph.schemas import (
    AgentTrace,
    DefenseChecks,
    DefenseReview,
    MayorData,
    MicroData,
    MicroDataSegment,
    Panel,
    PanelSegment,
    SearchResult,
    UsableAnswer,
)
from app.llm.types import LLMMessage
from tests.checkpoint_fakes import FakeBinaryRedis, FakeBinaryRedisAsync

TTL = 1234

# langgraph sentinel channels: NO_WRITES marks "node ran, wrote nothing" and
# must round-trip — dropping it would re-run completed no-op nodes on resume.
ERROR_CHANNEL = "__error__"
NO_WRITES_CHANNEL = "__no_writes__"


def _mk_checkpoint(suffix: str, channel_values: dict | None = None) -> dict:
    # UUIDv6-shaped ids: lexicographic order == chronological order.
    return {
        "v": 1,
        "id": f"1f000000-0000-6000-8000-{suffix:0>12}",
        "ts": "2026-07-27T00:00:00+00:00",
        "channel_values": dict(channel_values or {}),
        "channel_versions": {"__start__": 1},
        "versions_seen": {},
        "updated_channels": None,
        "pending_sends": [],
    }


def _thread_cfg(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}


@pytest.fixture()
def fakes(monkeypatch):
    sync_fake = FakeBinaryRedis()
    async_fake = FakeBinaryRedisAsync(sync_fake)  # shared storage across legs
    monkeypatch.setattr(
        "app.graph.checkpoint.create_binary_sync_redis", lambda: sync_fake
    )
    monkeypatch.setattr(
        "app.graph.checkpoint.create_binary_async_redis", lambda: async_fake
    )
    return sync_fake, async_fake


@pytest.fixture()
def saver(fakes) -> RedisCheckpointSaver:
    return RedisCheckpointSaver(ttl_seconds=TTL)


# --- 1. the shared contract body (future live-Redis leg calls this too) -----


def _assert_checkpointer_contract(saver: RedisCheckpointSaver) -> None:
    thread_id = "sess-1:panel-1"
    cfg = _thread_cfg(thread_id)

    cp1 = _mk_checkpoint("1")
    cfg1 = saver.put(cfg, cp1, {"source": "input", "step": -1, "parents": {}}, {})
    assert cfg1["configurable"]["checkpoint_id"] == cp1["id"]

    cp2 = _mk_checkpoint("2", {"collected_data": ["alpha"]})
    cfg2 = saver.put(cfg1, cp2, {"source": "loop", "step": 0, "parents": {}}, {})

    # latest wins without an explicit checkpoint_id
    latest = saver.get_tuple(_thread_cfg(thread_id))
    assert latest is not None
    assert latest.checkpoint["id"] == cp2["id"]
    assert latest.checkpoint["channel_values"] == {"collected_data": ["alpha"]}
    assert latest.parent_config["configurable"]["checkpoint_id"] == cp1["id"]

    # exact fetch by checkpoint_id; the root has no parent
    first = saver.get_tuple(cfg1)
    assert first is not None
    assert first.checkpoint["id"] == cp1["id"]
    assert first.parent_config is None

    # pending writes surface on the checkpoint they were stored against
    saver.put_writes(cfg2, [("collected_data", ["beta"])], task_id="task-a")
    assert saver.get_tuple(cfg2).pending_writes == [
        ("task-a", "collected_data", ["beta"])
    ]
    assert saver.get_tuple(cfg1).pending_writes == []

    # list: UUIDv6-descending, before/limit, metadata filter
    ids = [t.checkpoint["id"] for t in saver.list(_thread_cfg(thread_id))]
    assert ids == [cp2["id"], cp1["id"]]
    ids = [
        t.checkpoint["id"]
        for t in saver.list(_thread_cfg(thread_id), before=cfg2, limit=1)
    ]
    assert ids == [cp1["id"]]
    ids = [
        t.checkpoint["id"]
        for t in saver.list(_thread_cfg(thread_id), filter={"source": "input"})
    ]
    assert ids == [cp1["id"]]

    # a second thread is invisible to the first
    other = saver.put(
        _thread_cfg("other-thread"),
        _mk_checkpoint("9"),
        {"source": "input", "step": -1, "parents": {}},
        {},
    )
    assert [t.checkpoint["id"] for t in saver.list(_thread_cfg(thread_id))] == [
        cp2["id"],
        cp1["id"],
    ]

    # delete_thread removes everything for that thread and nothing else
    saver.delete_thread(thread_id)
    assert saver.get_tuple(cfg1) is None
    assert list(saver.list(_thread_cfg(thread_id))) == []
    assert saver.get_tuple(other) is not None


def test_checkpointer_contract_fake_backed(saver) -> None:
    _assert_checkpointer_contract(saver)


# --- 2-4. writes semantics ---------------------------------------------------


def test_put_writes_idempotent_on_task_and_idx(saver) -> None:
    cfg = saver.put(
        _thread_cfg("t"), _mk_checkpoint("1"), {"source": "loop", "step": 0}, {}
    )
    saver.put_writes(cfg, [("collected_data", ["first"])], task_id="t1")
    saver.put_writes(cfg, [("collected_data", ["second"])], task_id="t1")
    assert saver.get_tuple(cfg).pending_writes == [
        ("t1", "collected_data", ["first"])  # idx >= 0 is write-once
    ]

    assert ERROR_CHANNEL in WRITES_IDX_MAP  # sanity: special channel, idx -1
    saver.put_writes(cfg, [(ERROR_CHANNEL, "boom-1")], task_id="t1")
    saver.put_writes(cfg, [(ERROR_CHANNEL, "boom-2")], task_id="t1")
    writes = saver.get_tuple(cfg).pending_writes
    assert ("t1", ERROR_CHANNEL, "boom-2") in writes  # negatives overwrite


def test_no_writes_sentinel_round_trips(saver) -> None:
    cfg = saver.put(
        _thread_cfg("t"), _mk_checkpoint("1"), {"source": "loop", "step": 0}, {}
    )
    saver.put_writes(cfg, [(NO_WRITES_CHANNEL, None)], task_id="noop-task")
    assert saver.get_tuple(cfg).pending_writes == [
        ("noop-task", NO_WRITES_CHANNEL, None)
    ]


def test_pending_writes_sorted_and_typed(saver) -> None:
    cfg = saver.put(
        _thread_cfg("t"), _mk_checkpoint("1"), {"source": "loop", "step": 0}, {}
    )
    saver.put_writes(
        cfg, [("collected_data", ["z1"]), ("search_queries", ["z2"])], task_id="zz"
    )
    saver.put_writes(cfg, [("collected_data", ["a1"])], task_id="aa")
    writes = saver.get_tuple(cfg).pending_writes
    assert writes == [
        ("aa", "collected_data", ["a1"]),
        ("zz", "collected_data", ["z1"]),
        ("zz", "search_queries", ["z2"]),
    ]


# --- 5. every state-carried pydantic model survives as its class -------------

_MODEL_INSTANCES = [
    AgentTrace(agent_name="chemistry", inputs_seen=["q"], task_summary="s"),
    SearchResult(query="q", url="https://x", title="t", excerpt="e"),
    MayorData(source_agent="chemistry", content="c", topic="t", pov="chem"),
    MicroDataSegment(title="t", content="c", source_agents=["a"]),
    MicroData(
        segments=[MicroDataSegment(title="t", content="c")], source_agents=["a"]
    ),
    UsableAnswer(
        segment_id="s1", order_hint=1, title="t", content="c", review_status="approved"
    ),
    DefenseChecks(big_picture="pass", detail="pass", implication="revise"),
    DefenseReview(
        segment_id="s1",
        checks=DefenseChecks(big_picture="pass", detail="pass", implication="pass"),
        verdict="pass",
    ),
    PanelSegment(title="t", content="c", pov="art"),
    Panel(
        panel_id="p1",
        folder_path="/f",
        status="completed",
        content_type="markdown",
        content="hello",
        data_tier="final",
        agent_traces=[AgentTrace(agent_name="a", inputs_seen=[])],
        pov_segments=[PanelSegment(title="t", content="c")],
    ),
    LLMMessage(role="user", content="hi"),
]


@pytest.mark.parametrize(
    "instance", _MODEL_INSTANCES, ids=lambda m: type(m).__name__
)
def test_serialization_round_trip_all_models_as_class(saver, instance) -> None:
    restored = saver.serde.loads_typed(saver.serde.dumps_typed(instance))
    assert type(restored) is type(instance), (
        f"{type(instance).__name__} degraded to {type(restored).__name__}"
    )
    assert restored == instance


def test_round_trip_covers_all_11_models() -> None:
    # Composition guard: the battery above must cover every model class.
    assert sorted(type(m).__name__ for m in _MODEL_INSTANCES) == sorted(
        [
            "AgentTrace",
            "SearchResult",
            "MayorData",
            "MicroDataSegment",
            "MicroData",
            "UsableAnswer",
            "DefenseChecks",
            "DefenseReview",
            "PanelSegment",
            "Panel",
            "LLMMessage",
        ]
    )


# --- 6. loud wrapper ----------------------------------------------------------


class _DegradingSerde:
    """Simulates the framework failure mode: pydantic values come back as raw
    dicts with no exception (jsonplus ext hook, reconstruction-failure path)."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def dumps_typed(self, obj):
        return self._inner.dumps_typed(obj)

    def loads_typed(self, data):
        obj = self._inner.loads_typed(data)
        if isinstance(obj, dict):
            values = obj.get("channel_values")
            if isinstance(values, dict) and "panels" in values:
                values["panels"] = [p.model_dump() for p in values["panels"]]
        return obj


def test_loud_wrapper_raises_on_degraded_dict(saver) -> None:
    panel = Panel(
        panel_id="p1",
        folder_path="/f",
        status="processing",
        content_type="markdown",
        content="c",
    )
    cfg = saver.put(
        _thread_cfg("t"),
        _mk_checkpoint("1", {"panels": [panel]}),
        {"source": "loop", "step": 0},
        {},
    )
    assert saver.get_tuple(cfg) is not None  # healthy round-trip first

    saver.serde = _DegradingSerde(saver.serde)
    with pytest.raises(CheckpointDeserializationError) as excinfo:
        saver.get_tuple(cfg)
    message = str(excinfo.value)
    assert "panels" in message and "[0]" in message


def test_loud_wrapper_covers_write_values(saver) -> None:
    cfg = saver.put(
        _thread_cfg("t"), _mk_checkpoint("1"), {"source": "loop", "step": 0}, {}
    )
    mayor = MayorData(source_agent="chemistry", content="c")
    saver.put_writes(cfg, [("mayor_data", [mayor])], task_id="t1")
    assert saver.get_tuple(cfg).pending_writes[0][2] == [mayor]

    class _DegradeWrites:
        def __init__(self, inner) -> None:
            self._inner = inner

        def dumps_typed(self, obj):
            return self._inner.dumps_typed(obj)

        def loads_typed(self, data):
            obj = self._inner.loads_typed(data)
            if isinstance(obj, list) and obj and isinstance(obj[0], MayorData):
                return [m.model_dump() for m in obj]
            return obj

    saver.serde = _DegradeWrites(saver.serde)
    with pytest.raises(CheckpointDeserializationError):
        saver.get_tuple(cfg)


# --- 7. channel-model map derivation (drift alarm) ----------------------------


def test_channel_model_map_matches_graphstate() -> None:
    assert _CHANNEL_MODEL_TYPES == {
        "search_results": (SearchResult, True),
        "mayor_data": (MayorData, True),
        "conversation_history": (LLMMessage, True),
        "panels": (Panel, True),
        "agent_traces": (AgentTrace, True),
        "micro_data": (MicroData, False),
        "usable_answers": (UsableAnswer, True),
        "defense_reviews": (DefenseReview, True),
    }


# --- 8-9. copy safety and TTL --------------------------------------------------


def test_saver_shallow_copy_safe(saver) -> None:
    clone = copy.copy(saver)  # the with_allowlist path uses copy.copy
    assert clone is not saver
    assert clone.serde is saver.serde
    cfg = clone.put(
        _thread_cfg("t"), _mk_checkpoint("1"), {"source": "input", "step": -1}, {}
    )
    assert saver.get_tuple(cfg).checkpoint["id"].endswith("1")


def test_ttl_applied_to_every_key(saver, fakes) -> None:
    sync_fake, _ = fakes
    cfg = saver.put(
        _thread_cfg("t"), _mk_checkpoint("1"), {"source": "loop", "step": 0}, {}
    )
    saver.put_writes(cfg, [("collected_data", ["x"])], task_id="t1")
    created = sync_fake.all_keys()
    assert created, "no keys created"
    for key in created:
        assert sync_fake.ttls.get(key) == TTL, f"missing/wrong TTL on {key!r}"


# --- 10. sync/async leg parity --------------------------------------------------


def _drive_sequence_sync(saver: RedisCheckpointSaver) -> None:
    cp1 = _mk_checkpoint("1")
    cfg1 = saver.put(_thread_cfg("t"), cp1, {"source": "input", "step": -1}, {})
    cp2 = _mk_checkpoint("2", {"collected_data": ["alpha"]})
    cfg2 = saver.put(cfg1, cp2, {"source": "loop", "step": 0}, {})
    saver.put_writes(cfg2, [("collected_data", ["beta"])], task_id="t1")
    saver.put_writes(cfg2, [(NO_WRITES_CHANNEL, None)], task_id="t2")


def _drive_sequence_async(saver: RedisCheckpointSaver) -> None:
    async def _run() -> None:
        cp1 = _mk_checkpoint("1")
        cfg1 = await saver.aput(
            _thread_cfg("t"), cp1, {"source": "input", "step": -1}, {}
        )
        cp2 = _mk_checkpoint("2", {"collected_data": ["alpha"]})
        cfg2 = await saver.aput(cfg1, cp2, {"source": "loop", "step": 0}, {})
        await saver.aput_writes(cfg2, [("collected_data", ["beta"])], task_id="t1")
        await saver.aput_writes(cfg2, [(NO_WRITES_CHANNEL, None)], task_id="t2")

        # async read path returns the same shape the sync path does
        tup = await saver.aget_tuple(_thread_cfg("t"))
        assert tup.checkpoint["id"] == cp2["id"]
        listed = []
        async for t in saver.alist(_thread_cfg("t")):
            listed.append(t.checkpoint["id"])
        assert listed == [cp2["id"], cp1["id"]]
        await saver.aclose()

    asyncio.run(_run())


def test_sync_async_legs_byte_identical(monkeypatch) -> None:
    sync_store = FakeBinaryRedis()
    async_store = FakeBinaryRedis()
    monkeypatch.setattr(
        "app.graph.checkpoint.create_binary_sync_redis", lambda: sync_store
    )
    monkeypatch.setattr(
        "app.graph.checkpoint.create_binary_async_redis",
        lambda: FakeBinaryRedisAsync(async_store),
    )

    _drive_sequence_sync(RedisCheckpointSaver(ttl_seconds=TTL))
    _drive_sequence_async(RedisCheckpointSaver(ttl_seconds=TTL))

    assert sync_store.dump() == async_store.dump()
    assert sync_store.ttls == async_store.ttls
