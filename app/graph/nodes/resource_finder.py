import logging
from typing import Any

from app.core.config import settings
from app.graph.schemas import AgentTrace, SearchResult
from app.graph.state import GraphState
from app.graph.trace_utils import truncate_preview
from app.search.cache import get_cached_hits, set_cached_hits
from app.search.provider import search_urls

logger = logging.getLogger(__name__)


async def resource_finder_node(state: GraphState) -> dict[str, Any]:
    """Locate URLs for the WR search query."""
    queries = state.get("search_queries") or []
    if not queries:
        logger.info("Resource Finder: no search queries; skipping")
        return {}

    query = queries[0]
    session_id = state.get("session_id", "")
    logger.info("Resource Finder searching for: %s", query)

    hits = get_cached_hits(session_id, query)
    if hits is None:
        hits = await search_urls(query, max_results=settings.search_max_urls)
        set_cached_hits(session_id, query, hits)

    search_results = [
        SearchResult(query=query, url=hit.url, title=hit.title, excerpt="")
        for hit in hits
    ]

    url_preview = ", ".join(hit.url for hit in hits[:3]) if hits else "no URLs found"
    finder_trace = AgentTrace(
        agent_name="resource_finder",
        inputs_seen=[f"search_query: {query}"],
        task_summary=state.get("current_task") or None,
        output_preview=truncate_preview(url_preview),
    )

    return {
        "search_results": search_results,
        "agent_traces": [finder_trace],
    }
