import logging
from typing import Any

from app.graph.state import GraphState

logger = logging.getLogger(__name__)


async def fan_in_wait_node(_state: GraphState) -> dict[str, Any]:
    """No-op sink for parallel branches that reach post_fan_in before all peers finish."""
    logger.debug("Fan-in wait: branch parked until remaining peers complete")
    return {}
