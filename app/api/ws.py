import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio.client import PubSub

from app.core.redis import (
    OPS_PROVIDER_CHANGED_CHANNEL,
    create_async_redis,
    session_channel,
)
from app.core.session_control import (
    get_active_task,
    revoke_active_task,
    set_active_task,
    set_interrupt,
)
from app.worker import process_user_input

logger = logging.getLogger(__name__)

router = APIRouter()


async def _forward_redis_messages(pubsub: PubSub, websocket: WebSocket) -> None:
    """Listen to Redis Pub/Sub and forward messages to the WebSocket client."""
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                payload = json.loads(message["data"])
            except json.JSONDecodeError:
                logger.warning("Skipping invalid JSON from Redis: %s", message["data"])
                continue

            await websocket.send_json(payload)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Redis listener failed")
        try:
            await websocket.send_json(
                {"type": "error", "message": "Redis subscription failed."}
            )
        except Exception:
            pass


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    """Stream Panels to the client and dispatch user input to Celery."""
    await websocket.accept()
    channel = session_channel(session_id)
    redis_client = create_async_redis()
    pubsub = redis_client.pubsub()
    redis_task: asyncio.Task[None] | None = None

    try:
        await pubsub.subscribe(channel, OPS_PROVIDER_CHANGED_CHANNEL)
        redis_task = asyncio.create_task(_forward_redis_messages(pubsub, websocket))

        try:
            from app.ops.balancer import assign_session

            assignment = assign_session(session_id)
            provider = None
            from app.ops.store import get_store

            provider = get_store().get_provider(assignment.provider_id)
            await websocket.send_json(
                {
                    "type": "session_assigned",
                    "session_id": session_id,
                    "provider_id": assignment.provider_id,
                    "policy": assignment.policy.value,
                    "ws_base_url": (
                        provider.effective_ws_base_url() if provider else None
                    ),
                }
            )
        except Exception:
            logger.debug("session assign skipped for %s", session_id, exc_info=True)

        while True:
            user_message = await websocket.receive_text()

            try:
                if get_active_task(session_id):
                    set_interrupt(session_id)
                    revoke_active_task(session_id)

                async_result = process_user_input.delay(user_message, session_id)
                set_active_task(session_id, async_result.id)
            except Exception as exc:
                logger.exception("Failed to dispatch Celery task for session %s", session_id)
                await websocket.send_json(
                    {"type": "error", "message": f"Failed to dispatch task: {exc}"}
                )
    except WebSocketDisconnect:
        logger.info("Client disconnected from session %s", session_id)
    finally:
        if redis_task is not None:
            redis_task.cancel()
            try:
                await redis_task
            except asyncio.CancelledError:
                pass

        await pubsub.unsubscribe(channel, OPS_PROVIDER_CHANGED_CHANNEL)
        await pubsub.aclose()
        await redis_client.aclose()
