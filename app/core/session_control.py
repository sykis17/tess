"""Redis-backed session task tracking and mid-chain interrupt flags."""

from __future__ import annotations

import logging

from app.core.config import settings
from app.core.redis import create_sync_redis

logger = logging.getLogger(__name__)

SESSION_KEY_TTL_SECONDS = 900


class SessionInterrupted(Exception):
    """Raised when the user steers away from the in-flight pipeline."""


def _active_task_key(session_id: str) -> str:
    return f"session:{session_id}:active_task"


def _interrupt_key(session_id: str) -> str:
    return f"session:{session_id}:interrupt"


def set_active_task(session_id: str, task_id: str) -> None:
    """Record the Celery task id currently processing this session."""
    if not session_id or not task_id:
        return
    client = create_sync_redis()
    try:
        client.set(_active_task_key(session_id), task_id, ex=SESSION_KEY_TTL_SECONDS)
    finally:
        client.close()


def get_active_task(session_id: str) -> str | None:
    """Return the active Celery task id for a session, if any."""
    if not session_id:
        return None
    client = create_sync_redis()
    try:
        value = client.get(_active_task_key(session_id))
        return value if value else None
    finally:
        client.close()


def clear_active_task(session_id: str) -> None:
    """Remove the active task record for a session."""
    if not session_id:
        return
    client = create_sync_redis()
    try:
        client.delete(_active_task_key(session_id))
    finally:
        client.close()


def clear_active_task_if_matches(session_id: str, task_id: str) -> None:
    """Clear the active task only when it still points at this task id."""
    if not session_id or not task_id:
        return
    if get_active_task(session_id) == task_id:
        clear_active_task(session_id)


def set_interrupt(session_id: str, target_task_id: str | None = None) -> None:
    """Mark a session as interrupted so the worker stops between nodes.

    Stores the TARGETED task id when known (W3): a resumed run is a different
    task id, so a stale flag aimed at the revoked task can never abort it even
    if a clear races. The legacy value "1" interrupts every observer.
    """
    if not session_id:
        return
    client = create_sync_redis()
    try:
        client.set(
            _interrupt_key(session_id),
            target_task_id or "1",
            ex=SESSION_KEY_TTL_SECONDS,
        )
    finally:
        client.close()


def clear_interrupt(session_id: str) -> None:
    """Clear the interrupt flag for a fresh run."""
    if not session_id:
        return
    client = create_sync_redis()
    try:
        client.delete(_interrupt_key(session_id))
    finally:
        client.close()


def is_session_interrupted(session_id: str, observer_task_id: str | None = None) -> bool:
    """Return whether the session has an active interrupt flag.

    Observer-scoped (W3): a flag valued with a DIFFERENT task id does not
    interrupt this observer; "1" (legacy / unknown target) interrupts everyone.
    The mid-node call sites stay unscoped deliberately — unscoped reads can
    only over-stop a run, never let one escape an interrupt.
    """
    if not session_id:
        return False
    client = create_sync_redis()
    try:
        value = client.get(_interrupt_key(session_id))
    finally:
        client.close()
    if value is None:
        return False
    if observer_task_id and value != "1" and value != observer_task_id:
        return False
    return True


def _resumable_thread_key(session_id: str) -> str:
    return f"session:{session_id}:resumable_thread"


def set_resumable_thread(session_id: str, thread_id: str) -> None:
    """Record the run's checkpoint thread as resumable.

    Written at run START (not at interrupt) so both interrupt and hard crash
    leave a handle; cleared on successful completion. TTL matches the
    checkpoint TTL — a handle must never outlive its checkpoints.
    """
    if not session_id or not thread_id:
        return
    client = create_sync_redis()
    try:
        client.set(
            _resumable_thread_key(session_id),
            thread_id,
            ex=settings.graph_checkpoint_ttl_seconds,
        )
    finally:
        client.close()


def get_resumable_thread(session_id: str) -> str | None:
    """Return the resumable checkpoint thread for a session, if any."""
    if not session_id:
        return None
    client = create_sync_redis()
    try:
        value = client.get(_resumable_thread_key(session_id))
        return value if value else None
    finally:
        client.close()


def clear_resumable_thread(session_id: str) -> None:
    """Drop the resumable handle (run completed; nothing left to resume)."""
    if not session_id:
        return
    client = create_sync_redis()
    try:
        client.delete(_resumable_thread_key(session_id))
    finally:
        client.close()


def revoke_active_task(session_id: str) -> None:
    """Revoke and clear the in-flight Celery task for a session."""
    task_id = get_active_task(session_id)
    if not task_id:
        return

    from app.worker import celery_app

    logger.info("Revoking task %s for session %s", task_id, session_id)
    celery_app.control.revoke(task_id, terminate=True)
    clear_active_task(session_id)
