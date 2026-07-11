import asyncio
import logging
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchHit:
    """A single URL result from a search provider."""

    title: str
    url: str


async def _search_tavily(query: str, max_results: int) -> list[SearchHit]:
    """Search via Tavily API when an API key is configured."""
    from tavily import AsyncTavilyClient

    client = AsyncTavilyClient(api_key=settings.tavily_api_key)
    response = await client.search(query=query, max_results=max_results)
    results = response.get("results", [])
    hits: list[SearchHit] = []
    for item in results:
        url = item.get("url", "")
        title = item.get("title", url)
        if url:
            hits.append(SearchHit(title=title, url=url))
    return hits


async def _search_duckduckgo(query: str, max_results: int) -> list[SearchHit]:
    """Search via DuckDuckGo (no API key required)."""
    from duckduckgo_search import DDGS

    def _run_search() -> list[SearchHit]:
        hits: list[SearchHit] = []
        with DDGS() as ddgs:
            for item in ddgs.text(query, max_results=max_results):
                url = item.get("href", "") or item.get("link", "")
                title = item.get("title", url)
                if url:
                    hits.append(SearchHit(title=title, url=url))
        return hits

    return await asyncio.to_thread(_run_search)


async def search_urls(query: str, max_results: int | None = None) -> list[SearchHit]:
    """Locate URLs for a query using Tavily (if configured) or DuckDuckGo."""
    limit = max_results if max_results is not None else settings.search_max_urls

    if settings.tavily_api_key:
        try:
            hits = await _search_tavily(query, limit)
            if hits:
                logger.info("Tavily returned %d results for query: %s", len(hits), query)
                return hits
            logger.warning("Tavily returned no results; falling back to DuckDuckGo")
        except Exception as exc:
            logger.warning("Tavily search failed; falling back to DuckDuckGo: %s", exc)

    try:
        hits = await _search_duckduckgo(query, limit)
        logger.info("DuckDuckGo returned %d results for query: %s", len(hits), query)
        return hits
    except Exception as exc:
        logger.error("DuckDuckGo search failed for query %s: %s", query, exc)
        return []
