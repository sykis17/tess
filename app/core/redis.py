import redis
import redis.asyncio as aioredis

from app.core.config import settings

OPS_PROVIDER_CHANGED_CHANNEL = "ops:provider_changed"


def session_channel(session_id: str) -> str:
    """Return the Redis Pub/Sub channel name for a given session."""
    return f"channel_{session_id}"


def create_sync_redis() -> redis.Redis:
    """Create a synchronous Redis client for Celery worker publishing."""
    return redis.from_url(settings.redis_url, decode_responses=True)


def create_async_redis() -> aioredis.Redis:
    """Create an async Redis client for FastAPI Pub/Sub subscription."""
    return aioredis.from_url(settings.redis_url, decode_responses=True)


def create_binary_sync_redis() -> redis.Redis:
    """Binary-safe sync client for the graph checkpointer.

    The checkpoint serializer emits msgpack bytes; decode_responses=True would
    UTF-8-mangle them silently, so the saver never uses the factories above.
    """
    return redis.from_url(settings.redis_url, decode_responses=False)


def create_binary_async_redis() -> aioredis.Redis:
    """Binary-safe async client for the graph checkpointer (see sync twin)."""
    return aioredis.from_url(settings.redis_url, decode_responses=False)
