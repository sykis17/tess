import asyncio
import logging
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger(__name__)

_SEARCH_BACKENDS = ("duckduckgo", "wikipedia", "brave", "bing")


@dataclass(frozen=True)
class SearchHit:
    """A single URL result from a search provider."""

    title: str
    url: str


def _hits_from_results(results: list[dict[str, str]], limit: int) -> list[SearchHit]:
    """Parse provider result dicts into SearchHit objects."""
    hits: list[SearchHit] = []
    seen_urls: set[str] = set()
    for item in results:
        if not item:
            continue
        url = item.get("href", "") or item.get("link", "") or item.get("url", "")
        title = item.get("title", "") or url
        if url and url not in seen_urls:
            seen_urls.add(url)
            hits.append(SearchHit(title=title, url=url))
        if len(hits) >= limit:
            break
    return hits


async def _search_tavily(query: str, max_results: int) -> list[SearchHit]:
    """Search via Tavily API when an API key is configured."""
    from tavily import AsyncTavilyClient

    client = AsyncTavilyClient(api_key=settings.tavily_api_key)
    response = await client.search(query=query, max_results=max_results)
    if not response or not isinstance(response, dict):
        return []

    results = response.get("results") or []
    hits: list[SearchHit] = []
    for item in results:
        if not item:
            continue
        url = item.get("url", "")
        title = item.get("title", url)
        if url:
            hits.append(SearchHit(title=title, url=url))
    return hits


async def _search_ddgs(query: str, max_results: int) -> list[SearchHit]:
    """Search via DDGS metasearch (no API key required)."""
    from ddgs import DDGS

    def _run_search() -> list[SearchHit]:
        for backend in _SEARCH_BACKENDS:
            try:
                results = DDGS().text(query, max_results=max_results, backend=backend)
                if not results:
                    logger.info("DDGS backend %s returned no results for: %s", backend, query)
                    continue
                hits = _hits_from_results(results, max_results)
                if hits:
                    logger.info(
                        "DDGS backend %s returned %d results for: %s",
                        backend,
                        len(hits),
                        query,
                    )
                    return hits
            except Exception as exc:
                logger.warning("DDGS backend %s failed for %s: %s", backend, query, exc)
        return []

    return await asyncio.to_thread(_run_search)


async def search_urls(query: str, max_results: int | None = None) -> list[SearchHit]:
    """Locate URLs for a query using Tavily (if configured) or DDGS."""
    limit = max_results if max_results is not None else settings.search_max_urls

    if settings.tavily_api_key:
        try:
            hits = await _search_tavily(query, limit)
            if hits:
                logger.info("Tavily returned %d results for query: %s", len(hits), query)
                return hits
            logger.warning("Tavily returned no results; falling back to DDGS")
        except Exception as exc:
            logger.warning("Tavily search failed; falling back to DDGS: %s", exc)

    try:
        hits = await _search_ddgs(query, limit)
        if hits:
            logger.info("DDGS returned %d results for query: %s", len(hits), query)
        else:
            logger.warning("DDGS returned no results for query: %s", query)
        return hits
    except Exception as exc:
        logger.error("DDGS search failed for query %s: %s", query, exc)
        return []
