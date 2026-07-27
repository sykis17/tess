"""Bytes-faithful in-memory Redis fake for checkpoint-saver tests.

decode_responses=False semantics throughout: keys, fields, members, and values
are stored and returned as bytes (str inputs are UTF-8-encoded, like redis-py).
Same idiom as tests/fence_fakes.py — a tiny purpose-built behavioural fake
injected by monkeypatching the client factory. close() only counts calls so the
sync leg's open-per-call convention can keep reusing one instance across calls.
"""

from __future__ import annotations

from typing import Any


def _b(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, (int, float)):
        return str(value).encode("utf-8")
    raise TypeError(f"unsupported redis value type: {type(value)!r}")


class FakeBinaryRedis:
    def __init__(self) -> None:
        self.hashes: dict[bytes, dict[bytes, bytes]] = {}
        self.zsets: dict[bytes, set[bytes]] = {}
        self.sets: dict[bytes, set[bytes]] = {}
        self.ttls: dict[bytes, int] = {}
        self.close_calls = 0

    def dump(self) -> tuple[dict, dict, dict]:
        """Storage snapshot for byte-identity parity assertions."""
        return (self.hashes, self.zsets, self.sets)

    def all_keys(self) -> set[bytes]:
        return set(self.hashes) | set(self.zsets) | set(self.sets)

    # -- redis command surface (subset the saver uses) ------------------------

    def hset(self, key, field=None, value=None, mapping=None) -> int:
        bucket = self.hashes.setdefault(_b(key), {})
        added = 0
        if field is not None:
            if _b(field) not in bucket:
                added += 1
            bucket[_b(field)] = _b(value)
        for f, v in (mapping or {}).items():
            if _b(f) not in bucket:
                added += 1
            bucket[_b(f)] = _b(v)
        return added

    def hsetnx(self, key, field, value) -> int:
        bucket = self.hashes.setdefault(_b(key), {})
        f = _b(field)
        if f in bucket:
            return 0
        bucket[f] = _b(value)
        return 1

    def hgetall(self, key) -> dict[bytes, bytes]:
        return dict(self.hashes.get(_b(key), {}))

    def zadd(self, key, mapping) -> int:
        zset = self.zsets.setdefault(_b(key), set())
        added = 0
        for member in mapping:
            m = _b(member)
            if m not in zset:
                added += 1
            zset.add(m)
        return added

    def zrevrangebylex(self, key, max, min, start=None, num=None) -> list[bytes]:  # noqa: A002
        members = sorted(self.zsets.get(_b(key), set()), reverse=True)

        def _ok(member: bytes, bound: bytes, upper: bool) -> bool:
            if bound == (b"+" if upper else b"-"):
                return True
            if bound == (b"-" if upper else b"+"):
                return False
            if bound.startswith(b"["):
                return member <= bound[1:] if upper else member >= bound[1:]
            if bound.startswith(b"("):
                return member < bound[1:] if upper else member > bound[1:]
            raise ValueError(f"bad lex bound: {bound!r}")

        out = [
            m
            for m in members
            if _ok(m, _b(max), upper=True) and _ok(m, _b(min), upper=False)
        ]
        if start is not None:
            end = None if num is None else start + num
            out = out[start:end]
        return out

    def sadd(self, key, *members) -> int:
        bucket = self.sets.setdefault(_b(key), set())
        added = 0
        for member in members:
            m = _b(member)
            if m not in bucket:
                added += 1
            bucket.add(m)
        return added

    def smembers(self, key) -> set[bytes]:
        return set(self.sets.get(_b(key), set()))

    def delete(self, *keys) -> int:
        removed = 0
        for key in keys:
            k = _b(key)
            for store in (self.hashes, self.zsets, self.sets):
                if k in store:
                    del store[k]
                    removed += 1
            self.ttls.pop(k, None)
        return removed

    def expire(self, key, ttl) -> bool:
        self.ttls[_b(key)] = int(ttl)
        return True

    def pipeline(self, transaction: bool = True) -> "_FakePipeline":
        return _FakePipeline(self)

    def close(self) -> None:
        self.close_calls += 1


class _FakePipeline:
    """Queues commands and applies them on execute() (like redis-py)."""

    def __init__(self, parent: FakeBinaryRedis) -> None:
        self._parent = parent
        self._ops: list[tuple[Any, tuple, dict]] = []

    def __getattr__(self, name: str):
        target = getattr(self._parent, name)

        def _queue(*args, **kwargs):
            self._ops.append((target, args, kwargs))
            return self

        return _queue

    def execute(self) -> list[Any]:
        ops, self._ops = self._ops, []
        return [fn(*args, **kwargs) for fn, args, kwargs in ops]


class FakeBinaryRedisAsync:
    """Async twin delegating to a sync FakeBinaryRedis.

    No pytest-asyncio in this suite — tests drive async saver legs via
    asyncio.run (house convention). Command methods that only queue on a
    pipeline stay synchronous, mirroring redis.asyncio.
    """

    def __init__(self, inner: FakeBinaryRedis | None = None) -> None:
        self.inner = inner or FakeBinaryRedis()

    async def hgetall(self, key) -> dict[bytes, bytes]:
        return self.inner.hgetall(key)

    async def zrevrangebylex(self, key, max, min, start=None, num=None):  # noqa: A002
        return self.inner.zrevrangebylex(key, max, min, start=start, num=num)

    async def smembers(self, key) -> set[bytes]:
        return self.inner.smembers(key)

    async def delete(self, *keys) -> int:
        return self.inner.delete(*keys)

    def pipeline(self, transaction: bool = True) -> "_FakeAsyncPipeline":
        return _FakeAsyncPipeline(self.inner)

    async def aclose(self) -> None:
        self.inner.close_calls += 1


class _FakeAsyncPipeline(_FakePipeline):
    """redis.asyncio pipelines queue synchronously; only execute() is awaited."""

    async def execute(self) -> list[Any]:  # type: ignore[override]
        return _FakePipeline.execute(self)
