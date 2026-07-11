import logging
from typing import Any

from app.graph.schemas import AgentTrace, MayorData, SearchResult
from app.graph.state import GraphState
from app.graph.trace_utils import truncate_preview
from app.search.extractor import html_to_text, make_excerpt
from app.search.fetcher import fetch_page_text

logger = logging.getLogger(__name__)


async def _read_result(result: SearchResult) -> SearchResult:
    """Fetch a URL and populate its excerpt."""
    html = await fetch_page_text(result.url)
    if html is None:
        return result

    text = html_to_text(html)
    excerpt = make_excerpt(text) if text else ""
    return result.model_copy(update={"excerpt": excerpt})


async def resource_reader_node(state: GraphState) -> dict[str, Any]:
    """Fetch pages and extract readable excerpts from search results."""
    search_results: list[SearchResult] = state.get("search_results") or []
    if not search_results:
        logger.info("Resource Reader: no search results; skipping")
        return {}

    logger.info("Resource Reader processing %d URLs", len(search_results))

    read_results: list[SearchResult] = []
    for result in search_results:
        try:
            read = await _read_result(result)
            if read.excerpt:
                read_results.append(read)
            else:
                logger.warning("No excerpt extracted from %s", result.url)
        except Exception as exc:
            logger.warning("Failed to read %s: %s", result.url, exc)

    if not read_results:
        reader_trace = AgentTrace(
            agent_name="resource_reader",
            inputs_seen=[r.url for r in search_results],
            task_summary=state.get("current_task") or None,
            output_preview="No excerpts extracted from search results.",
        )
        return {"agent_traces": [reader_trace]}

    content_lines: list[str] = []
    citations: list[str] = []

    for result in read_results:
        content_lines.append(f"### {result.title}\n\n{result.excerpt}\n\nSource: {result.url}")
        citations.append(f"[{result.title}]({result.url})")

    mayor_entry = MayorData(
        source_agent="resource_reader",
        content="\n\n".join(content_lines),
        topic="Web sources",
        citations=citations,
    )

    url_inputs = [r.url for r in search_results]
    reader_trace = AgentTrace(
        agent_name="resource_reader",
        inputs_seen=url_inputs,
        task_summary=state.get("current_task") or None,
        output_preview=truncate_preview(
            f"{len(read_results)} excerpt(s) from {read_results[0].url}"
        ),
    )

    return {
        "mayor_data": [mayor_entry],
        "agent_traces": [reader_trace],
    }
