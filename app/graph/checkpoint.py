"""Redis-backed LangGraph checkpoint saver (W3).

Doctrine: checkpoints are recoverable-loss run scratch — a lost checkpoint
means the run restarts; never corruption, never split authority — which is what
keeps them compatible with the post-cutover "Redis = caches + pub/sub" contract
(see deploy/MULTI_CLOUD.md). Threads are strictly per-run
(thread_id = f"{session_id}:{panel_id}") and never outlive their turn;
conversation:{session_id} remains the sole cross-turn store.

Key schema (all keys TTL'd on every write, refreshed as the run progresses):
  graph:ckpt:{thread}:{ns}:{id}         HASH   serialized checkpoint + metadata
  graph:ckpt-index:{thread}:{ns}        ZSET   checkpoint ids (UUIDv6: lex==time)
  graph:ckpt-writes:{thread}:{ns}:{id}  HASH   pending writes per (task_id, idx)
  graph:ckpt-keys:{thread}              SET    key registry (delete without SCAN)

Never-silent doctrine: the framework serializer degrades a failed pydantic
reconstruction to a raw kwargs dict WITHOUT raising (jsonplus ext hook), so
every load re-validates model-bearing channels and raises
CheckpointDeserializationError instead of letting a dict flow into the graph.
"""

from __future__ import annotations

import asyncio
import json
from importlib.metadata import version as _pkg_version
from inspect import isclass
from types import UnionType
from typing import (
    Annotated,
    Any,
    AsyncIterator,
    Iterator,
    Sequence,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

import ormsgpack
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import BaseModel

from app.core.config import settings
from app.core.redis import create_binary_async_redis, create_binary_sync_redis
from app.graph import schemas as _schemas
from app.graph.state import GraphState
from app.llm.types import LLMMessage


class CheckpointDeserializationError(RuntimeError):
    """A checkpointed value came back as a raw dict instead of its model."""


def _build_serde() -> JsonPlusSerializer:
    # Allowlist entries are exact (module, name) pairs; passing the classes is
    # the unambiguous form, and deriving them from the schemas module means a
    # new model can never drift out of the allowlist.
    allowed: list[type] = [
        obj
        for obj in vars(_schemas).values()
        if isclass(obj) and issubclass(obj, BaseModel)
    ]
    allowed.append(LLMMessage)
    return JsonPlusSerializer(allowed_msgpack_modules=allowed)


def _derive_channel_model_types() -> dict[str, tuple[type[BaseModel], bool]]:
    """Map GraphState channels to their pydantic element type.

    Derived from the type hints, not hand-maintained — the same
    can't-drift-beats-drift-detected move as test_reducer_keys agreement.
    Value: (model, is_list).
    """
    derived: dict[str, tuple[type[BaseModel], bool]] = {}
    for name, hint in get_type_hints(GraphState, include_extras=True).items():
        if get_origin(hint) is Annotated or hasattr(hint, "__metadata__"):
            hint = get_args(hint)[0]
        origin = get_origin(hint)
        if origin is list:
            elem = get_args(hint)[0]
            if isclass(elem) and issubclass(elem, BaseModel):
                derived[name] = (elem, True)
        elif origin in (Union, UnionType):
            args = [a for a in get_args(hint) if a is not type(None)]
            if len(args) == 1 and isclass(args[0]) and issubclass(args[0], BaseModel):
                derived[name] = (args[0], False)
    return derived


_CHANNEL_MODEL_TYPES = _derive_channel_model_types()

_FW_VERSIONS = json.dumps(
    {
        "langgraph": _pkg_version("langgraph"),
        "langchain_core": _pkg_version("langchain-core"),
    },
    sort_keys=True,
)


def _ckpt_key(thread_id: str, ns: str, checkpoint_id: str) -> str:
    return f"graph:ckpt:{thread_id}:{ns}:{checkpoint_id}"


def _index_key(thread_id: str, ns: str) -> str:
    return f"graph:ckpt-index:{thread_id}:{ns}"


def _writes_key(thread_id: str, ns: str, checkpoint_id: str) -> str:
    return f"graph:ckpt-writes:{thread_id}:{ns}:{checkpoint_id}"


def _registry_key(thread_id: str) -> str:
    return f"graph:ckpt-keys:{thread_id}"


def _thread_ns(config: RunnableConfig) -> tuple[str, str]:
    conf = config.get("configurable", {})
    thread_id = str(conf.get("thread_id") or "")
    if not thread_id:
        raise ValueError("checkpoint config missing configurable.thread_id")
    return thread_id, str(conf.get("checkpoint_ns") or "")


def _checkpoint_config(thread_id: str, ns: str, checkpoint_id: str) -> RunnableConfig:
    return {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": ns,
            "checkpoint_id": checkpoint_id,
        }
    }


def _validate_value(channel: str, value: Any, context: str) -> None:
    spec = _CHANNEL_MODEL_TYPES.get(channel)
    if spec is None:
        return
    model, is_list = spec
    if is_list:
        if not isinstance(value, list):
            return
        for i, item in enumerate(value):
            if not isinstance(item, model):
                raise CheckpointDeserializationError(
                    f"{context}: channel {channel!r}[{i}] degraded to "
                    f"{type(item).__name__} — expected {model.__name__}; "
                    "serializer reconstruction failed"
                )
    elif value is not None and not isinstance(value, model):
        raise CheckpointDeserializationError(
            f"{context}: channel {channel!r} degraded to "
            f"{type(value).__name__} — expected {model.__name__}; "
            "serializer reconstruction failed"
        )


def _validate_channel_values(channel_values: dict[str, Any], context: str) -> None:
    for channel, value in channel_values.items():
        _validate_value(channel, value, context)


class RedisCheckpointSaver(BaseCheckpointSaver[int]):
    """Durable checkpointer over the existing redis dependency.

    Inherits the default integer get_next_version — langgraph calls it
    synchronously even on the async path, so it must never do I/O. Instances
    must stay shallow-copy-safe (with_allowlist uses copy.copy): no per-run
    mutable state beyond the loop-stamped client below.
    """

    def __init__(self, *, ttl_seconds: int) -> None:
        super().__init__(serde=_build_serde())
        self._ttl = int(ttl_seconds)
        self._aclient = None
        self._aclient_loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def from_settings(cls) -> "RedisCheckpointSaver":
        # Settings read at call time, never import time (harness zero-infra).
        return cls(ttl_seconds=settings.graph_checkpoint_ttl_seconds)

    # -- async client lifecycle ------------------------------------------------

    def _aclient_for_current_loop(self):
        loop = asyncio.get_running_loop()
        if self._aclient is None or self._aclient_loop is not loop:
            # Effectively one fresh client per Celery task: asyncio.run gives
            # each task a new loop; the previous loop is closed, so its
            # connections die with it and the dropped client is GC-collected.
            # Understood and bounded at worker --concurrency=1.
            self._aclient = create_binary_async_redis()
            self._aclient_loop = loop
        return self._aclient

    async def aclose(self) -> None:
        """Close the held client if it belongs to the running loop.

        Callers must finalize the graph stream (await stream.aclose()) first —
        Pregel's exit-stack flush may still need this client.
        """
        if self._aclient is not None and self._aclient_loop is asyncio.get_running_loop():
            await self._aclient.aclose()
            self._aclient = None
            self._aclient_loop = None

    # -- shared payload/pipeline helpers (correctness lives once) ---------------

    def _checkpoint_mapping(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
    ) -> dict[bytes, bytes]:
        ckpt_type, ckpt_blob = self.serde.dumps_typed(dict(checkpoint))
        meta_type, meta_blob = self.serde.dumps_typed(
            get_checkpoint_metadata(config, metadata)
        )
        parent_id = get_checkpoint_id(config) or ""
        return {
            b"checkpoint_type": ckpt_type.encode(),
            b"checkpoint_data": ckpt_blob,
            b"metadata_type": meta_type.encode(),
            b"metadata_data": meta_blob,
            b"parent_checkpoint_id": parent_id.encode(),
            b"fw_versions": _FW_VERSIONS.encode(),
        }

    def _queue_put(self, pipe, thread_id: str, ns: str, checkpoint_id: str, mapping):
        key = _ckpt_key(thread_id, ns, checkpoint_id)
        index = _index_key(thread_id, ns)
        registry = _registry_key(thread_id)
        pipe.hset(key, mapping=mapping)
        pipe.zadd(index, {checkpoint_id: 0})
        pipe.sadd(registry, key, index)
        for k in (key, index, registry):
            pipe.expire(k, self._ttl)
        return pipe

    def _write_entries(
        self, writes: Sequence[tuple[str, Any]], task_id: str, task_path: str
    ) -> list[tuple[str, bytes, bool]]:
        entries = []
        for idx, (channel, value) in enumerate(writes):
            idx_key = WRITES_IDX_MAP.get(channel, idx)
            value_type, value_blob = self.serde.dumps_typed(value)
            packed = ormsgpack.packb([channel, task_path, value_type, value_blob])
            entries.append((f"{task_id}:{idx_key}", packed, idx_key >= 0))
        return entries

    def _queue_put_writes(self, pipe, thread_id, ns, checkpoint_id, entries):
        wkey = _writes_key(thread_id, ns, checkpoint_id)
        index = _index_key(thread_id, ns)
        registry = _registry_key(thread_id)
        for field, packed, write_once in entries:
            if write_once:
                pipe.hsetnx(wkey, field, packed)  # write-once per (task_id, idx)
            else:
                pipe.hset(wkey, field, packed)  # ERROR/INTERRUPT/... overwrite
        pipe.sadd(registry, wkey)
        for k in (wkey, index, registry):
            pipe.expire(k, self._ttl)
        return pipe

    def _load_tuple(
        self,
        thread_id: str,
        ns: str,
        checkpoint_id: str,
        ckpt_hash: dict[bytes, bytes],
        writes_hash: dict[bytes, bytes],
    ) -> CheckpointTuple | None:
        if not ckpt_hash:
            return None
        context = f"checkpoint {checkpoint_id} (thread {thread_id!r})"
        checkpoint = self.serde.loads_typed(
            (ckpt_hash[b"checkpoint_type"].decode(), ckpt_hash[b"checkpoint_data"])
        )
        _validate_channel_values(checkpoint.get("channel_values") or {}, context)
        metadata = self.serde.loads_typed(
            (ckpt_hash[b"metadata_type"].decode(), ckpt_hash[b"metadata_data"])
        )
        parent_id = ckpt_hash.get(b"parent_checkpoint_id", b"").decode()
        pending: list[tuple[int, str, str, Any]] = []
        for field, packed in writes_hash.items():
            task_id, idx_str = field.decode().rsplit(":", 1)
            channel, _task_path, value_type, value_blob = ormsgpack.unpackb(packed)
            value = self.serde.loads_typed((value_type, value_blob))
            _validate_value(channel, value, context)
            pending.append((int(idx_str), task_id, channel, value))
        pending.sort(key=lambda e: (e[1], e[0]))
        return CheckpointTuple(
            config=_checkpoint_config(thread_id, ns, checkpoint_id),
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=(
                _checkpoint_config(thread_id, ns, parent_id) if parent_id else None
            ),
            pending_writes=[(t, c, v) for _i, t, c, v in pending],
        )

    @staticmethod
    def _metadata_matches(metadata: CheckpointMetadata, flt: dict[str, Any]) -> bool:
        return all(metadata.get(k) == v for k, v in flt.items())

    @staticmethod
    def _lex_bounds(before: RunnableConfig | None) -> bytes:
        if before is not None and (before_id := get_checkpoint_id(before)):
            return b"(" + before_id.encode()
        return b"+"

    # -- sync leg (opens/closes a client per call; rare path: state tooling) ----

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id, ns = _thread_ns(config)
        checkpoint_id = checkpoint["id"]
        mapping = self._checkpoint_mapping(config, checkpoint, metadata)
        client = create_binary_sync_redis()
        try:
            self._queue_put(
                client.pipeline(), thread_id, ns, checkpoint_id, mapping
            ).execute()
        finally:
            client.close()
        return _checkpoint_config(thread_id, ns, checkpoint_id)

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id, ns = _thread_ns(config)
        checkpoint_id = get_checkpoint_id(config)
        if not checkpoint_id:
            raise ValueError("put_writes config missing configurable.checkpoint_id")
        entries = self._write_entries(writes, task_id, task_path)
        client = create_binary_sync_redis()
        try:
            self._queue_put_writes(
                client.pipeline(), thread_id, ns, checkpoint_id, entries
            ).execute()
        finally:
            client.close()

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id, ns = _thread_ns(config)
        client = create_binary_sync_redis()
        try:
            checkpoint_id = get_checkpoint_id(config)
            if not checkpoint_id:
                ids = client.zrevrangebylex(
                    _index_key(thread_id, ns), b"+", b"-", start=0, num=1
                )
                if not ids:
                    return None
                checkpoint_id = ids[0].decode()
            ckpt_hash = client.hgetall(_ckpt_key(thread_id, ns, checkpoint_id))
            writes_hash = client.hgetall(_writes_key(thread_id, ns, checkpoint_id))
        finally:
            client.close()
        return self._load_tuple(thread_id, ns, checkpoint_id, ckpt_hash, writes_hash)

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        if config is None:
            raise ValueError("RedisCheckpointSaver.list requires configurable.thread_id")
        thread_id, ns = _thread_ns(config)
        client = create_binary_sync_redis()
        results: list[CheckpointTuple] = []
        try:
            ids = client.zrevrangebylex(
                _index_key(thread_id, ns), self._lex_bounds(before), b"-"
            )
            for raw in ids:
                checkpoint_id = raw.decode()
                tup = self._load_tuple(
                    thread_id,
                    ns,
                    checkpoint_id,
                    client.hgetall(_ckpt_key(thread_id, ns, checkpoint_id)),
                    client.hgetall(_writes_key(thread_id, ns, checkpoint_id)),
                )
                if tup is None:
                    continue
                if filter and not self._metadata_matches(tup.metadata, filter):
                    continue
                results.append(tup)
                if limit is not None and len(results) >= limit:
                    break
        finally:
            client.close()
        yield from results

    def delete_thread(self, thread_id: str) -> None:
        registry = _registry_key(thread_id)
        client = create_binary_sync_redis()
        try:
            members = client.smembers(registry)
            client.delete(*members, registry)
        finally:
            client.close()

    # -- async leg (what the async Pregel loop binds) ----------------------------

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id, ns = _thread_ns(config)
        checkpoint_id = checkpoint["id"]
        mapping = self._checkpoint_mapping(config, checkpoint, metadata)
        client = self._aclient_for_current_loop()
        await self._queue_put(
            client.pipeline(), thread_id, ns, checkpoint_id, mapping
        ).execute()
        return _checkpoint_config(thread_id, ns, checkpoint_id)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id, ns = _thread_ns(config)
        checkpoint_id = get_checkpoint_id(config)
        if not checkpoint_id:
            raise ValueError("aput_writes config missing configurable.checkpoint_id")
        entries = self._write_entries(writes, task_id, task_path)
        client = self._aclient_for_current_loop()
        await self._queue_put_writes(
            client.pipeline(), thread_id, ns, checkpoint_id, entries
        ).execute()

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id, ns = _thread_ns(config)
        client = self._aclient_for_current_loop()
        checkpoint_id = get_checkpoint_id(config)
        if not checkpoint_id:
            ids = await client.zrevrangebylex(
                _index_key(thread_id, ns), b"+", b"-", start=0, num=1
            )
            if not ids:
                return None
            checkpoint_id = ids[0].decode()
        ckpt_hash = await client.hgetall(_ckpt_key(thread_id, ns, checkpoint_id))
        writes_hash = await client.hgetall(_writes_key(thread_id, ns, checkpoint_id))
        return self._load_tuple(thread_id, ns, checkpoint_id, ckpt_hash, writes_hash)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        if config is None:
            raise ValueError("RedisCheckpointSaver.alist requires configurable.thread_id")
        thread_id, ns = _thread_ns(config)
        client = self._aclient_for_current_loop()
        ids = await client.zrevrangebylex(
            _index_key(thread_id, ns), self._lex_bounds(before), b"-"
        )
        count = 0
        for raw in ids:
            checkpoint_id = raw.decode()
            tup = self._load_tuple(
                thread_id,
                ns,
                checkpoint_id,
                await client.hgetall(_ckpt_key(thread_id, ns, checkpoint_id)),
                await client.hgetall(_writes_key(thread_id, ns, checkpoint_id)),
            )
            if tup is None:
                continue
            if filter and not self._metadata_matches(tup.metadata, filter):
                continue
            yield tup
            count += 1
            if limit is not None and count >= limit:
                return

    async def adelete_thread(self, thread_id: str) -> None:
        registry = _registry_key(thread_id)
        client = self._aclient_for_current_loop()
        members = await client.smembers(registry)
        await client.delete(*members, registry)
