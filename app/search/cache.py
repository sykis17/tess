import hashlib
import json
import logging

from app.core.config import settings
from app.core.redis import create_sync_redis
from app.search.provider import SearchHit

logger = logging.getLogger(__name__)


def _cache_key(session_id: str, query: str) -> str:
    digest = hashlib.sha256(query.encode()).hexdigest()[:16]
    return f"search:{session_id}:{digest}"


def get_cached_hits(session_id: str, query: str) -> list[SearchHit] | None:
    """Return cached search hits for a session query, or None on miss."""
    if not session_id:
        return None

    redis_client = create_sync_redis()
    try:
        raw = redis_client.get(_cache_key(session_id, query))
        if raw is None:
            return None
        data = json.loads(raw)
        return [SearchHit(title=item["title"], url=item["url"]) for item in data]
    except Exception as exc:
        logger.warning("Search cache read failed: %s", exc)
        return None
    finally:
        redis_client.close()


def set_cached_hits(session_id: str, query: str, hits: list[SearchHit]) -> None:
    """Cache search hits for a session query."""
    if not session_id or not hits:
        return

    redis_client = create_sync_redis()
    try:
        payload = json.dumps([{"title": h.title, "url": h.url} for h in hits])
        redis_client.setex(
            _cache_key(session_id, query),
            settings.search_cache_ttl_seconds,
            payload,
        )
    except Exception as exc:
        logger.warning("Search cache write failed: %s", exc)
    finally:
        redis_client.close()
