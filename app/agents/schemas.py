from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    """Configuration for a specialist agent."""

    name: str
    folder_path: str
    description: str
    system_prompt: str


class RoutingDecision(BaseModel):
    """Structured routing output from the Wide Receiver."""

    active_agents: list[str] = Field(min_length=1)
    current_task: str = Field(min_length=1)
