"""W3 resume-path gates (plan tests 17-22).

Test 17 is THE W3 gate: interrupt a run mid-fan-out, resume, and no branch
double-executes. Test 18 is its PERMANENT red leg — the identical scenario
without a checkpointer re-executes the completed branch, so "must fail with
the flag off" stays encoded forever instead of being a one-time ritual.
Both drive the real Pregel loop over the fake-backed RedisCheckpointSaver;
no live LLM anywhere.
"""

from __future__ import annotations

import asyncio
import operator
import time
from typing import Annotated, Callable, TypedDict
from unittest.mock import MagicMock, patch

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

import app.api.ws as ws_module
import app.core.session_control as session_control
import app.worker as worker_module
from app.core.config import settings
from app.graph.checkpoint import RedisCheckpointSaver
from app.graph.schemas import Panel
from tests.checkpoint_fakes import FakeBinaryRedis, FakeBinaryRedisAsync


class _FanState(TypedDict):
    done: Annotated[list[str], operator.add]


def _fan_graph(
    checkpointer,
    counters: dict[str, int],
    fail_once: dict[str, bool],
    a_write_visible: Callable[[], bool],
):
    """Two-branch fan-out via Send; branch_b aborts the first pass only after
    branch_a's completion is observable, making the interrupt point exact."""
    builder = StateGraph(_FanState)
    builder.add_node("receiver", lambda state: {})  # exercises NO_WRITES for real

    def branch_a(state):
        counters["a"] += 1
        return {"done": ["a"]}

    async def branch_b(state):
        if fail_once.get("armed"):
            fail_once["armed"] = False
            deadline = time.monotonic() + 2.0
            while not a_write_visible() and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.02)  # let branch_a's put_writes settle
            raise RuntimeError("controlled mid-fan-out abort")
        counters["b"] += 1
        return {"done": ["b"]}

    builder.add_node("branch_a", branch_a)
    builder.add_node("branch_b", branch_b)
    builder.add_edge(START, "receiver")
    builder.add_conditional_edges(
        "receiver", lambda state: [Send("branch_a", state), Send("branch_b", state)]
    )
    builder.add_edge("branch_a", END)
    builder.add_edge("branch_b", END)
    return builder.compile(checkpointer=checkpointer)


async def _consume(stream) -> list[str]:
    nodes: list[str] = []
    async for update in stream:
        nodes.extend(update.keys())
    return nodes


def _fake_store(monkeypatch) -> FakeBinaryRedis:
    store = FakeBinaryRedis()
    monkeypatch.setattr("app.graph.checkpoint.create_binary_sync_redis", lambda: store)
    monkeypatch.setattr(
        "app.graph.checkpoint.create_binary_async_redis",
        lambda: FakeBinaryRedisAsync(store),
    )
    return store


def _done_write_recorded(store: FakeBinaryRedis) -> Callable[[], bool]:
    def _visible() -> bool:
        return any(
            key.startswith(b"graph:ckpt-writes:")
            and any(b"done" in value for value in fields.values())
            for key, fields in store.hashes.items()
        )

    return _visible


# --- 17-18. THE gate and its permanent red leg --------------------------------


def test_resume_after_interrupt_no_double_execution(monkeypatch) -> None:
    store = _fake_store(monkeypatch)
    counters = {"a": 0, "b": 0}
    graph = _fan_graph(
        RedisCheckpointSaver(ttl_seconds=60),
        counters,
        {"armed": True},
        _done_write_recorded(store),
    )
    cfg = {"configurable": {"thread_id": "sess-1:panel-1"}}

    with pytest.raises(RuntimeError, match="controlled mid-fan-out abort"):
        asyncio.run(
            _consume(
                graph.astream(
                    {"done": []}, cfg, stream_mode="updates", durability="sync"
                )
            )
        )
    assert counters == {"a": 1, "b": 0}, "branch_a must complete before the abort"

    # Resume: input=None + same thread_id == resume-after-interrupt. The
    # framework rehydrates branch_a's recorded writes and ticks only the
    # writeless task — no double execution, given a correct durable saver.
    nodes = asyncio.run(
        _consume(graph.astream(None, cfg, stream_mode="updates", durability="sync"))
    )
    assert counters == {"a": 1, "b": 1}, "branch_a double-executed on resume"
    assert "branch_b" in nodes
    # branch_a also appears in the resume stream — as a REPLAYED update: the
    # loop re-emits rehydrated writes without executing the node (the counter
    # above is the double-execution proof). Consequence for panel delivery:
    # completed nodes' terminal panels republish on resume via the post-node
    # path — the idempotent-replace case; only streaming deltas need dedup (C4).
    final = asyncio.run(graph.aget_state(cfg))
    assert sorted(final.values["done"]) == ["a", "b"], "continuation incoherent"


def test_resume_impossible_without_checkpointer() -> None:
    counters = {"a": 0, "b": 0}
    graph = _fan_graph(
        None, counters, {"armed": True}, lambda: counters["a"] >= 1
    )
    with pytest.raises(RuntimeError, match="controlled mid-fan-out abort"):
        asyncio.run(_consume(graph.astream({"done": []}, stream_mode="updates")))
    assert counters == {"a": 1, "b": 0}

    # Without a checkpointer the only way forward is a from-scratch re-run:
    # the completed branch executes AGAIN. This is the failure mode W3 removes
    # — if this assertion ever starts failing, the gate above went vacuous.
    asyncio.run(_consume(graph.astream({"done": []}, stream_mode="updates")))
    assert counters["a"] == 2, "expected double execution without a checkpointer"
    assert counters["b"] == 1


# --- 19. ws resume entry --------------------------------------------------------


class _RecordingWS:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


def test_ws_resume_refused_while_task_active(monkeypatch) -> None:
    ws = _RecordingWS()
    fake_task = MagicMock()
    monkeypatch.setattr(ws_module, "get_active_task", lambda sid: "task-live")
    monkeypatch.setattr(ws_module, "resume_user_input", fake_task)
    asyncio.run(ws_module._handle_resume(ws, "sess-1"))
    assert ws.sent and ws.sent[0]["type"] == "error"
    assert "refused" in ws.sent[0]["message"]
    fake_task.delay.assert_not_called()


def test_ws_resume_nothing_to_resume(monkeypatch) -> None:
    ws = _RecordingWS()
    fake_task = MagicMock()
    monkeypatch.setattr(ws_module, "get_active_task", lambda sid: None)
    monkeypatch.setattr(ws_module, "get_resumable_thread", lambda sid: None)
    monkeypatch.setattr(ws_module, "resume_user_input", fake_task)
    asyncio.run(ws_module._handle_resume(ws, "sess-1"))
    assert ws.sent and ws.sent[0]["type"] == "error"
    fake_task.delay.assert_not_called()


def test_ws_resume_dispatches_when_idle(monkeypatch) -> None:
    ws = _RecordingWS()
    fake_task = MagicMock()
    fake_task.delay.return_value.id = "task-new"
    recorded: dict[str, str] = {}
    monkeypatch.setattr(ws_module, "get_active_task", lambda sid: None)
    monkeypatch.setattr(ws_module, "get_resumable_thread", lambda sid: "sess-1:p1")
    monkeypatch.setattr(ws_module, "resume_user_input", fake_task)
    monkeypatch.setattr(
        ws_module, "set_active_task", lambda sid, tid: recorded.update({sid: tid})
    )
    asyncio.run(ws_module._handle_resume(ws, "sess-1"))
    fake_task.delay.assert_called_once_with("sess-1", "sess-1:p1")
    assert recorded == {"sess-1": "task-new"}
    assert not ws.sent


def test_ws_resume_request_detection() -> None:
    assert ws_module._is_resume_request('{"type": "resume"}') is True
    assert ws_module._is_resume_request("plain text question") is False
    assert ws_module._is_resume_request('{"text": "hi", "product_mode": "auto"}') is False
    assert ws_module._is_resume_request("[1, 2]") is False


# --- 20. interrupt-flag observer scoping ----------------------------------------


def test_interrupt_flag_observer_scoping() -> None:
    mock_client = MagicMock()
    with patch(
        "app.core.session_control.create_sync_redis", return_value=mock_client
    ):
        session_control.set_interrupt("s1", target_task_id="task-A")
        mock_client.set.assert_called_once_with(
            "session:s1:interrupt", "task-A", ex=900
        )

        mock_client.get.return_value = "task-A"
        assert session_control.is_session_interrupted("s1") is True
        assert (
            session_control.is_session_interrupted("s1", observer_task_id="task-A")
            is True
        )
        # A stale flag aimed at the revoked task must not abort a resumed run.
        assert (
            session_control.is_session_interrupted("s1", observer_task_id="task-B")
            is False
        )

        mock_client.get.return_value = "1"  # legacy value interrupts everyone
        assert (
            session_control.is_session_interrupted("s1", observer_task_id="task-B")
            is True
        )

        mock_client.get.return_value = None
        assert (
            session_control.is_session_interrupted("s1", observer_task_id="task-B")
            is False
        )


def test_set_interrupt_without_target_keeps_legacy_value() -> None:
    mock_client = MagicMock()
    with patch(
        "app.core.session_control.create_sync_redis", return_value=mock_client
    ):
        session_control.set_interrupt("s1")
        mock_client.set.assert_called_once_with("session:s1:interrupt", "1", ex=900)


def test_resumable_thread_helpers() -> None:
    mock_client = MagicMock()
    with patch(
        "app.core.session_control.create_sync_redis", return_value=mock_client
    ):
        session_control.set_resumable_thread("s1", "s1:p1")
        mock_client.set.assert_called_once_with(
            "session:s1:resumable_thread",
            "s1:p1",
            ex=settings.graph_checkpoint_ttl_seconds,
        )
        mock_client.get.return_value = "s1:p1"
        assert session_control.get_resumable_thread("s1") == "s1:p1"
        session_control.clear_resumable_thread("s1")
        mock_client.delete.assert_called_with("session:s1:resumable_thread")


# --- 21. resume final state comes from the checkpoint, not the streamed merge ---


def _resume_env(monkeypatch, *, flag_on: bool = True):
    """Patch the worker's collaborators for a direct resume_user_input call."""
    monkeypatch.setattr(settings, "graph_checkpointing_enabled", flag_on)

    pre_values = {
        "user_input": "original question",
        "chain_profile": "L4",
        "product_mode": "auto",
        "panel_id": "p1",
        "session_id": "sess-1",
        "panels": [],
    }
    final_panel = Panel(
        panel_id="p1",
        folder_path="/f",
        status="completed",
        content_type="markdown",
        content="FINAL ANSWER",
    )
    post_values = dict(pre_values, panels=[final_panel])

    class _Snap:
        def __init__(self, values, next_):
            self.values = values
            self.next = next_

    snapshots = [_Snap(pre_values, ("branch_b",)), _Snap(post_values, ())]
    calls: dict = {}

    fake_graph = MagicMock()

    async def aget_state(config):
        calls.setdefault("aget_configs", []).append(config)
        return snapshots.pop(0)

    async def astream(*args, **kwargs):
        calls["astream_args"] = args
        calls["astream_kwargs"] = kwargs
        yield {"branch_b": {"panels": []}}

    fake_graph.aget_state = aget_state
    fake_graph.astream = astream

    class _StubSaver:
        async def aclose(self) -> None:
            calls.setdefault("saver_closes", 0)
            calls["saver_closes"] += 1

    appended: list[tuple] = []
    cleared: list[str] = []
    monkeypatch.setattr(worker_module, "get_checkpointed_graph", lambda: fake_graph)
    monkeypatch.setattr(worker_module, "get_checkpoint_saver", lambda: _StubSaver())
    monkeypatch.setattr(worker_module, "create_sync_redis", lambda: MagicMock())
    monkeypatch.setattr(worker_module, "clear_interrupt", lambda sid: None)
    monkeypatch.setattr(worker_module, "is_session_interrupted", lambda *a: False)
    monkeypatch.setattr(
        worker_module, "clear_active_task_if_matches", lambda sid, tid: None
    )
    monkeypatch.setattr(
        worker_module,
        "append_conversation_turn",
        lambda sid, user, content: appended.append((sid, user, content)),
    )
    monkeypatch.setattr(
        worker_module, "clear_resumable_thread", lambda sid: cleared.append(sid)
    )
    errors: list[str] = []
    monkeypatch.setattr(
        worker_module,
        "_publish_error",
        lambda client, channel, message: errors.append(message),
    )
    return calls, appended, cleared, errors


def test_resume_final_state_from_checkpoint_not_merged_dict(monkeypatch) -> None:
    calls, appended, cleared, errors = _resume_env(monkeypatch)
    worker_module.resume_user_input("sess-1", "sess-1:p1")

    # re-entry shape: input=None, same thread, durability pinned
    assert calls["astream_args"][0] is None
    assert calls["astream_args"][1] == {"configurable": {"thread_id": "sess-1:p1"}}
    assert calls["astream_kwargs"] == {"stream_mode": "updates", "durability": "sync"}

    # the conversation turn is recorded from CHECKPOINTED state — user text
    # from the pre-resume snapshot, content from the post-resume snapshot,
    # NOT from the streamed merge (whose panels were empty).
    assert appended == [("sess-1", "original question", "FINAL ANSWER")]
    assert cleared == ["sess-1"]
    assert errors == []


def test_resume_flag_off_publishes_error(monkeypatch) -> None:
    calls, appended, cleared, errors = _resume_env(monkeypatch, flag_on=False)
    worker_module.resume_user_input("sess-1", "sess-1:p1")
    assert errors and "disabled" in errors[0]
    assert "astream_args" not in calls
    assert appended == [] and cleared == []


def test_resume_with_nothing_pending_publishes_error(monkeypatch) -> None:
    calls, appended, cleared, errors = _resume_env(monkeypatch)

    class _EmptySnap:
        values: dict = {}
        next: tuple = ()

    async def aget_state(config):
        return _EmptySnap()

    worker_module.get_checkpointed_graph().aget_state = aget_state
    worker_module.resume_user_input("sess-1", "sess-1:p1")
    assert errors and "Nothing to resume" in errors[0]
    assert appended == []


# --- 22. replay reproduces the node sequence -------------------------------------


class _LinState(TypedDict):
    seen: Annotated[list[str], operator.add]


def test_replay_reproduces_node_sequence(monkeypatch) -> None:
    _fake_store(monkeypatch)
    saver = RedisCheckpointSaver(ttl_seconds=60)
    builder = StateGraph(_LinState)
    builder.add_node("n1", lambda s: {"seen": ["n1"]})
    builder.add_node("n2", lambda s: {"seen": ["n2"]})
    builder.add_edge(START, "n1")
    builder.add_edge("n1", "n2")
    builder.add_edge("n2", END)
    graph = builder.compile(checkpointer=saver)
    cfg = {"configurable": {"thread_id": "replay:1"}}

    original = asyncio.run(
        _consume(graph.astream({"seen": []}, cfg, stream_mode="updates", durability="sync"))
    )
    assert original == ["n1", "n2"]

    # checkpoint history is complete and ordered (alist yields newest-first)
    tuples = list(saver.list(cfg))
    steps = [t.metadata.get("step") for t in tuples]
    assert steps == sorted(steps, reverse=True)
    root = tuples[-1]
    assert root.metadata.get("source") == "input"

    # replay-from-checkpoint (the W5 debugging lever, proven now): re-entering
    # at the root checkpoint reproduces the same node sequence.
    replay_cfg = {
        "configurable": {
            "thread_id": "replay:1",
            "checkpoint_id": root.checkpoint["id"],
        }
    }
    replayed = asyncio.run(
        _consume(graph.astream(None, replay_cfg, stream_mode="updates", durability="sync"))
    )
    assert replayed == original
