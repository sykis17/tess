import operator
from typing import Annotated

from typing_extensions import TypedDict

from app.graph.schemas import Panel


class GraphState(TypedDict):
    """Shared LangGraph state schema for all orchestration nodes."""

    user_input: str
    current_task: str
    active_agents: list[str]
    collected_data: Annotated[list[str], operator.add]
    interruption_flag: bool
    panels: Annotated[list[Panel], operator.add]


def build_initial_state(user_input: str) -> GraphState:
    """Build the initial LangGraph state for a new user input."""
    return {
        "user_input": user_input,
        "current_task": "",
        "active_agents": [],
        "collected_data": [],
        "interruption_flag": False,
        "panels": [],
    }
