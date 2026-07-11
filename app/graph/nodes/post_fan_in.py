import logging
from typing import Any

from app.graph.combiner_utils import should_bypass_combiners
from app.graph.state import GraphState

logger = logging.getLogger(__name__)


async def post_fan_in_node(state: GraphState) -> dict[str, Any]:
    """Join parallel specialist and search branches; decide combiner bypass."""
    bypassed = should_bypass_combiners(state)
    mayor_count = len(state.get("mayor_data") or [])
    logger.info(
        "Post fan-in: mayor_data=%d entries, combiners_bypassed=%s",
        mayor_count,
        bypassed,
    )
    return {"combiners_bypassed": bypassed}
