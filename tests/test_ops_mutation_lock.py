"""Mutation-lock serialization for durable /ops/* writes (Quorum Fence Store step 5a).

Offloading the durable write to a thread (so the etcd-failover ladder never stalls the
event loop) restores true handler concurrency, which reopens a lost-update race: two
read-modify-write cycles under the same valid fence term would both be CAS-accepted
(CAS fences terms, not writers within a term) and the later stale full-blob snapshot
would clobber the first. ``app.api.ops._mutation_lock`` serializes every durable write
so the last writer always persists the latest in-memory state.

These tests bind a FRESH lock inside each test's own event loop (``asyncio.run`` makes a
new loop; the module-level lock would otherwise stay bound to the TestClient loop used
by the rest of the suite), so they are independent of test ordering.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time

import httpx
import pytest

import app.api.ops as ops
from app.core.config import settings
from app.main import app
from app.ops.consensus import InMemoryConsensus, set_consensus_backend
from app.ops.fencing import (
    clear_demote_callbacks,
    mark_primary,
    set_ha_disabled_role,
)
from app.ops.store import reset_store, set_fence_store

_TERM = 5
_TOKEN = "secret-token"


class _RecordingFenceStore:
    """Authoritative-store stand-in that records concurrency + the last durable blob.

    ``cas_persist`` sleeps briefly so that, absent serialization, two offloaded
    persists genuinely overlap — making ``max_concurrent`` a non-vacuous guard.
    """

    def __init__(self, term: int) -> None:
        self._term = term
        self.blob: str | None = None
        self.max_concurrent = 0
        self._active = 0
        self._guard = threading.Lock()

    def read_term(self) -> int:
        return self._term

    def read_blob(self) -> str | None:
        return self.blob

    def write_blob(self, payload: str) -> None:
        self.blob = payload

    def promote_term(self, term: int) -> bool:
        return self._term <= term

    def cas_persist(self, term: int, payload: str) -> bool:
        with self._guard:
            self._active += 1
            self.max_concurrent = max(self.max_concurrent, self._active)
        time.sleep(0.02)  # widen the overlap window if the lock were absent
        accept = term == self._term
        if accept:
            self.blob = payload
        with self._guard:
            self._active -= 1
        return accept


class _OKAdapter:
    def validate_connection(self, provider) -> dict:  # noqa: ANN001
        return {"ok": True}


@pytest.fixture(autouse=True)
def _lock_test_cleanup(monkeypatch: pytest.MonkeyPatch):
    clear_demote_callbacks()
    set_ha_disabled_role()
    set_consensus_backend(None)
    reset_store()
    yield
    clear_demote_callbacks()
    set_ha_disabled_role()
    set_consensus_backend(None)
    reset_store()


def _activate_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ops_ha_enabled", True)
    monkeypatch.setattr(settings, "ops_etcd_endpoints", "http://etcd:2379")
    monkeypatch.setattr(settings, "ops_persist_enabled", True)
    monkeypatch.setattr(settings, "ops_fence_authority", "etcd")
    monkeypatch.setattr(settings, "ops_cp_instance_id", "cp-a")
    monkeypatch.setattr(settings, "ops_admin_token", _TOKEN)
    monkeypatch.setattr(settings, "ops_admin_tokens", None)
    monkeypatch.setattr("app.api.ops.get_adapter", lambda _t: _OKAdapter())
    backend = InMemoryConsensus()
    backend.force_leader("cp-a", term=_TERM)
    set_consensus_backend(backend)
    mark_primary(_TERM, lease_id=1)


def test_two_concurrent_creates_no_lost_update(monkeypatch: pytest.MonkeyPatch) -> None:
    _activate_primary(monkeypatch)
    recording = _RecordingFenceStore(_TERM)
    set_fence_store(recording)

    headers = {"Authorization": f"Bearer {_TOKEN}"}
    body_a = {"type": "hetzner", "name": "A", "base_url": "http://a.example"}
    body_b = {"type": "aws", "name": "B", "base_url": "http://b.example"}

    async def _run():
        # Fresh lock bound to THIS loop (see module docstring).
        monkeypatch.setattr(ops, "_mutation_lock", asyncio.Lock())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            return await asyncio.gather(
                client.post("/ops/providers", json=body_a, headers=headers),
                client.post("/ops/providers", json=body_b, headers=headers),
            )

    r_a, r_b = asyncio.run(_run())

    assert r_a.status_code == 201, r_a.text
    assert r_b.status_code == 201, r_b.text

    # Serialization: the offloaded persists never overlapped (would be 2 without the lock).
    assert recording.max_concurrent == 1

    # Both writers survive in the last durable blob — no lost update.
    assert recording.blob is not None
    persisted_ids = set(json.loads(recording.blob)["providers"].keys())
    assert {r_a.json()["id"], r_b.json()["id"]} <= persisted_ids


def test_offloaded_write_and_async_lockwrap_share_one_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The compare/byo lock-wrap serializes against an offloaded _fenced_commit.

    This is the property that makes full-coverage race-free: a thread-borne persist
    (``_fenced_commit`` -> ``to_thread``) can never run in parallel with a loop-borne
    durable write in an async handler (``compare``/``byo``) because both hold the same
    ``_mutation_lock``.
    """
    state = {"active": 0, "max": 0}
    guard = threading.Lock()

    def _offloaded_write() -> None:
        with guard:
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
        time.sleep(0.02)
        with guard:
            state["active"] -= 1

    async def _run():
        monkeypatch.setattr(ops, "_mutation_lock", asyncio.Lock())

        async def _async_handler_lockwrap() -> None:  # mimics compare/byo
            async with ops._mutation_lock:
                with guard:
                    state["active"] += 1
                    state["max"] = max(state["max"], state["active"])
                await asyncio.sleep(0.02)
                with guard:
                    state["active"] -= 1

        await asyncio.gather(
            ops._fenced_commit(_offloaded_write),
            _async_handler_lockwrap(),
        )
        return state["max"]

    assert asyncio.run(_run()) == 1
