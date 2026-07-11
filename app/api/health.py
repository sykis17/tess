from fastapi import APIRouter, HTTPException

from app.core.redis import create_async_redis

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Return service health; verify Redis connectivity for orchestration probes."""
    redis_client = create_async_redis()
    try:
        await redis_client.ping()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail={"status": "unhealthy", "redis": "error"},
        )
    finally:
        await redis_client.aclose()

    return {"status": "ok", "redis": "ok"}
