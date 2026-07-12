import operator
from typing import Annotated

from typing_extensions import TypedDict

from app.graph.schemas import (
    AgentTrace,
    DefenseReview,
    MayorData,
    MicroData,
    Panel,
    SearchResult,
    UsableAnswer,
)
from app.llm.types import LLMMessage


class GraphState(TypedDict):
    """Shared LangGraph state schema for all orchestration nodes."""

    user_input: str
    current_task: str
    active_agents: list[str]
    search_queries: list[str]
    search_results: Annotated[list[SearchResult], operator.add]
    session_id: str
    collected_data: Annotated[list[str], operator.add]
    mayor_data: Annotated[list[MayorData], operator.add]
    conversation_history: list[LLMMessage]
    interruption_flag: bool
    panels: Annotated[list[Panel], operator.add]
    agent_traces: Annotated[list[AgentTrace], operator.add]
    panel_id: str
    micro_data: MicroData | None
    usable_answers: list[UsableAnswer]
    combiners_bypassed: bool
    defense_reviews: list[DefenseReview]
    defense_retry_count: int
    defense_notes: str
    expected_fan_in_branches: list[str]
    fan_in_branches_done: Annotated[list[str], operator.add]


def build_initial_state(
    user_input: str,
    conversation_history: list[LLMMessage] | None = None,
    panel_id: str = "",
    session_id: str = "",
) -> GraphState:
    """Build the initial LangGraph state for a new user input."""
    return {
        "user_input": user_input,
        "current_task": "",
        "active_agents": [],
        "search_queries": [],
        "search_results": [],
        "session_id": session_id,
        "collected_data": [],
        "mayor_data": [],
        "conversation_history": conversation_history or [],
        "interruption_flag": False,
        "panels": [],
        "agent_traces": [],
        "panel_id": panel_id,
        "micro_data": None,
        "usable_answers": [],
        "combiners_bypassed": False,
        "defense_reviews": [],
        "defense_retry_count": 0,
        "defense_notes": "",
        "expected_fan_in_branches": [],
        "fan_in_branches_done": [],
    }
