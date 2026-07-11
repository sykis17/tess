from app.agents.general_assistant.config import GENERAL_ASSISTANT_CONFIG
from app.agents.schemas import AgentConfig

AGENT_REGISTRY: dict[str, AgentConfig] = {
    GENERAL_ASSISTANT_CONFIG.name: GENERAL_ASSISTANT_CONFIG,
}

DEFAULT_AGENT_NAME = GENERAL_ASSISTANT_CONFIG.name


def get_agent(name: str) -> AgentConfig:
    """Return the configuration for a registered agent."""
    if name not in AGENT_REGISTRY:
        raise KeyError(f"Unknown agent: {name}")
    return AGENT_REGISTRY[name]


def list_agents_for_prompt() -> str:
    """Format registered agents for inclusion in the Wide Receiver routing prompt."""
    lines: list[str] = []
    for agent in AGENT_REGISTRY.values():
        lines.append(f'- "{agent.name}": {agent.description}')
    return "\n".join(lines)
