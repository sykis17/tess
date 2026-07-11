import operator
from typing import Annotated

from typing_extensions import TypedDict

from app.graph.schemas import AgentTrace, MayorData, Panel
from app.llm.types import LLMMessage


class GraphState(TypedDict):
    """Shared LangGraph state schema for all orchestration nodes."""

    user_input: str
    current_task: str
    active_agents: list[str]
    collected_data: Annotated[list[str], operator.add]
    mayor_data: Annotated[list[MayorData], operator.add]
    conversation_history: list[LLMMessage]
    interruption_flag: bool
    panels: Annotated[list[Panel], operator.add]
    agent_traces: Annotated[list[AgentTrace], operator.add]
    panel_id: str


def build_initial_state(
    user_input: str,
    conversation_history: list[LLMMessage] | None = None,
    panel_id: str = "",
) -> GraphState:
    """Build the initial LangGraph state for a new user input."""
    return {
        "user_input": user_input,
        "current_task": "",
        "active_agents": [],
        "collected_data": [],
        "mayor_data": [],
        "conversation_history": conversation_history or [],
        "interruption_flag": False,
        "panels": [],
        "agent_traces": [],
        "panel_id": panel_id,
    }
