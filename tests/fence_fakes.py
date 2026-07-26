"""Shared test fakes for the fence store backends."""

from __future__ import annotations

from app.ops.store import REDIS_CONTROL_PLANE_KEY, REDIS_FENCE_TERM_KEY


class _FakeRedis:
    """Minimal Redis stand-in that runs the fence Lua scripts (by substring match).

    Faithful to the two scripts in ``app/ops/store.py``:
    - promote: idempotent monotonic install (``cur <= nxt``)
    - persist CAS: write blob iff ``cur == term``
    """

    def __init__(self, *, fence_term: int = 0) -> None:
        self.kv: dict[str, str] = {}
        if fence_term:
            self.kv[REDIS_FENCE_TERM_KEY] = str(fence_term)

    def get(self, key: str) -> str | None:
        return self.kv.get(key)

    def set(self, key: str, value: str) -> None:
        self.kv[key] = value

    def eval(self, script: str, numkeys: int, *args: str) -> int:
        keys = list(args[:numkeys])
        argv = list(args[numkeys:])
        if "cur <= nxt" in script:
            # promote (idempotent monotonic install)
            cur = int(self.kv.get(keys[0], "0"))
            nxt = int(argv[0])
            if cur <= nxt:
                self.kv[keys[0]] = argv[0]
                return 1
            return 0
        if "cur == term" in script:
            cur = int(self.kv.get(keys[0], "0"))
            term = int(argv[0])
            if cur == term:
                self.kv[keys[1]] = argv[1]
                return 1
            return 0
        raise AssertionError(f"unexpected lua script: {script[:80]}")

    def close(self) -> None:
        return None


# Re-export keys so tests can assert on them without a second import.
__all__ = ["_FakeRedis", "REDIS_CONTROL_PLANE_KEY", "REDIS_FENCE_TERM_KEY"]
