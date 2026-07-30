import logging

import httpx

from app.core.config import settings
from app.core.egress_guard import ensure_egress_allowed

logger = logging.getLogger(__name__)

_MAX_RESPONSE_BYTES = 512_000
_USER_AGENT = (
    "Mozilla/5.0 (compatible; TESS-Engine/1.0; +https://github.com/sykis17/tess)"
)


async def fetch_page_text(url: str) -> str | None:
    """Fetch a URL and return raw HTML, or None on failure.

    Raises EgressRefusedError under sovereign-strict. This seam is guarded in
    addition to search_urls because cached search hits bypass the finder and
    reach the fetcher directly (resource_finder cache short-circuit).
    """
    ensure_egress_allowed("fetch_page_text", url)
    timeout = httpx.Timeout(settings.search_fetch_timeout_seconds)
    headers = {"User-Agent": _USER_AGENT}

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=headers,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                logger.warning("Skipping non-text content at %s (%s)", url, content_type)
                return None

            raw = response.content[:_MAX_RESPONSE_BYTES]
            return raw.decode(response.encoding or "utf-8", errors="replace")
    except httpx.HTTPError as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None
