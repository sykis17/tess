from fastapi import APIRouter, HTTPException, Request, Response

from app.core.redis import create_async_redis

router = APIRouter()


@router.api_route("/health", methods=["GET", "HEAD"], response_model=None)
async def health_check(request: Request) -> Response | dict[str, str]:
    """
    Return service health; verify Redis connectivity for orchestration probes.

    HEAD is required: external uptime checkers (e.g. UptimeRobot) often probe
    with HEAD; GET-only routes return 405 and look "Down".
    """
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

    payload = {"status": "ok", "redis": "ok"}
    if request.method == "HEAD":
        # Explicit empty body; status/headers still signal health to monitors.
        return Response(status_code=200, media_type="application/json")
    return payload
