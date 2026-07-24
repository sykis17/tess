"""Fencing helpers for ops control-plane HA.

Web process may cache role for early refusal. Celery must use
``check_fence_live()`` only — never cached role/term.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

from app.core.config import settings
from app.ops.consensus import LiveElection, get_consensus_backend

logger = logging.getLogger(__name__)


class FenceError(Exception):
    """Base class for fence failures (etcd or Redis CAS). Same severity."""


class NotPrimaryError(FenceError):
    """This instance is not the current etcd leader."""


class FenceCasError(FenceError):
    """Redis CAS rejected the write (stale fence term)."""


class PersistError(FenceError):
    """Redis persistence failed for a non-CAS reason."""


@dataclass
class RoleState:
    role: str  # primary | standby | demoted | ha_disabled
    fence_term: int | None = None
    lease_id: int | None = None
    primary_instance_id: str | None = None


_role_lock = threading.RLock()
_role = RoleState(role="ha_disabled")
_on_demote: list = []

# Per-task / per-request write term for persist_store CAS (never a module cache of "am I primary").
_write_fence_term: ContextVar[int | None] = ContextVar(
    "ops_write_fence_term", default=None
)


def register_demote_callback(cb) -> None:
    _on_demote.append(cb)


def clear_demote_callbacks() -> None:
    _on_demote.clear()


def get_role_state() -> RoleState:
    with _role_lock:
        return RoleState(
            role=_role.role,
            fence_term=_role.fence_term,
            lease_id=_role.lease_id,
            primary_instance_id=_role.primary_instance_id,
        )


def set_ha_disabled_role() -> None:
    with _role_lock:
        _role.role = "ha_disabled"
        _role.fence_term = None
        _role.lease_id = None
        _role.primary_instance_id = None


def mark_primary(fence_term: int, lease_id: int | None) -> None:
    with _role_lock:
        _role.role = "primary"
        _role.fence_term = fence_term
        _role.lease_id = lease_id
        _role.primary_instance_id = settings.ops_cp_instance_id


def mark_standby(*, primary_instance_id: str | None = None, fence_term: int | None = None) -> None:
    with _role_lock:
        _role.role = "standby"
        _role.fence_term = fence_term
        _role.lease_id = None
        _role.primary_instance_id = primary_instance_id


def demote(reason: str) -> None:
    """Leave primary role. Invokes registered callbacks (e.g. stop probe loop)."""
    with _role_lock:
        was_primary = _role.role == "primary"
        _role.role = "demoted"
        _role.lease_id = None
        # Keep last known term for diagnostics; do not use for writes.
    logger.error("CP demoted reason=%s", reason)
    if was_primary:
        for cb in list(_on_demote):
            try:
                cb(reason)
            except Exception:
                logger.exception("demote callback failed")


def check_fence_live() -> LiveElection:
    """Fresh etcd read. Raises NotPrimaryError unless we are the leader.

    When HA is disabled, returns a synthetic election with term 0 and our
    instance id as leader so single-node paths can proceed.
    """
    if not settings.ops_ha_active():
        return LiveElection(leader=settings.ops_cp_instance_id, fence_term=0)

    live = get_consensus_backend().read_election()
    if live.leader != settings.ops_cp_instance_id:
        raise NotPrimaryError(
            f"not primary: leader={live.leader!r} self={settings.ops_cp_instance_id!r} "
            f"term={live.fence_term}"
        )
    return live


def require_primary_cached() -> int:
    """Web early-refuse helper. Returns cached fence term or raises NotPrimaryError.

    Durable writes must still go through Redis CAS with an explicit term.
    Celery must not call this — use ``check_fence_live()`` instead.
    """
    if not settings.ops_ha_active():
        return 0
    with _role_lock:
        if _role.role != "primary" or _role.fence_term is None:
            raise NotPrimaryError(
                f"not primary (cached role={_role.role!r} term={_role.fence_term!r})"
            )
        return _role.fence_term


@contextmanager
def write_fence(term: int) -> Iterator[int]:
    """Bind the fence term used by ``persist_store`` for this call stack."""
    token = _write_fence_term.set(term)
    try:
        yield term
    finally:
        _write_fence_term.reset(token)


def current_write_fence_term() -> int | None:
    return _write_fence_term.get()


def resolve_write_fence_term(*, fence_term: int | None = None) -> int:
    """Resolve term for a durable write.

    Preference: explicit arg > contextvar > (web only) cached primary term.
    Celery paths must pass explicit term from ``check_fence_live()``.
    """
    if not settings.ops_ha_active():
        return 0 if fence_term is None else fence_term
    if fence_term is not None:
        return fence_term
    ctx = _write_fence_term.get()
    if ctx is not None:
        return ctx
    return require_primary_cached()


def commit_fenced(*, fence_term: int | None = None) -> None:
    """Persist with Redis CAS. On fence/CAS failure: store already restores+demotes; re-raise.

    ``FenceCasError`` and ``NotPrimaryError`` are treated with identical severity.
    """
    from app.ops.store import persist_store

    term = resolve_write_fence_term(fence_term=fence_term)
    try:
        persist_store(fence_term=term)
    except FenceError:
        # persist_store demotes+restores on CAS; ensure demote on other FenceErrors too
        if get_role_state().role == "primary":
            demote("fence_commit_failed")
        raise
