from typing import Literal

from pydantic import BaseModel, Field

AgentKind = Literal["pov", "tool", "media"]


class AgentConfig(BaseModel):
    """Configuration for a specialist agent."""

    name: str
    folder_path: str
    description: str
    system_prompt: str
    pov: str | None = None
    agent_kind: AgentKind = "tool"


class RoutingDecision(BaseModel):
    """Structured routing output from the Wide Receiver."""

    active_agents: list[str] = Field(min_length=1)
    current_task: str = Field(min_length=1)
    search_queries: list[str] = Field(default_factory=list)
