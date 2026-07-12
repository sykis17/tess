"""Redis-backed session task tracking and mid-chain interrupt flags."""

from __future__ import annotations

import logging

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


def set_interrupt(session_id: str) -> None:
    """Mark a session as interrupted so the worker stops between nodes."""
    if not session_id:
        return
    client = create_sync_redis()
    try:
        client.set(_interrupt_key(session_id), "1", ex=SESSION_KEY_TTL_SECONDS)
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


def is_session_interrupted(session_id: str) -> bool:
    """Return whether the session has an active interrupt flag."""
    if not session_id:
        return False
    client = create_sync_redis()
    try:
        return client.get(_interrupt_key(session_id)) is not None
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
