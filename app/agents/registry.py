from app.agents.audio.config import AUDIO_CONFIG
from app.agents.coder.config import CODER_CONFIG
from app.agents.general_assistant.config import GENERAL_ASSISTANT_CONFIG
from app.agents.photo.config import PHOTO_CONFIG
from app.agents.researcher.config import RESEARCHER_CONFIG
from app.agents.schemas import AgentConfig
from app.agents.video.config import VIDEO_CONFIG

AGENT_REGISTRY: dict[str, AgentConfig] = {
    GENERAL_ASSISTANT_CONFIG.name: GENERAL_ASSISTANT_CONFIG,
    CODER_CONFIG.name: CODER_CONFIG,
    RESEARCHER_CONFIG.name: RESEARCHER_CONFIG,
    PHOTO_CONFIG.name: PHOTO_CONFIG,
    VIDEO_CONFIG.name: VIDEO_CONFIG,
    AUDIO_CONFIG.name: AUDIO_CONFIG,
}

DEFAULT_AGENT_NAME = GENERAL_ASSISTANT_CONFIG.name

_DISPLAY_NAME_OVERRIDES: dict[str, str] = {
    "wide_receiver": "Wide Receiver",
    "presenter": "Presenter",
    "resource_finder": "Resource Finder",
    "resource_reader": "Resource Reader",
    "combiner_mayor": "Combiner Mayor",
    "combiner_micro": "Combiner Micro",
    "collector": "Collector",
    "defense_delegator": "Defense Delegator",
    "defense_review": "Defense Review",
    "photo": "Photo",
    "video": "Video",
    "audio": "Audio",
}


def get_agent(name: str) -> AgentConfig:
    """Return the configuration for a registered agent."""
    if name not in AGENT_REGISTRY:
        raise KeyError(f"Unknown agent: {name}")
    return AGENT_REGISTRY[name]


def format_agent_display_name(registry_key: str) -> str:
    """Convert a registry key to a human-readable display name."""
    if registry_key in _DISPLAY_NAME_OVERRIDES:
        return _DISPLAY_NAME_OVERRIDES[registry_key]

    if registry_key in AGENT_REGISTRY:
        return registry_key.replace("_", " ").title()

    return registry_key.replace("_", " ").title()


def list_agents_for_prompt() -> str:
    """Format registered agents for inclusion in the Wide Receiver routing prompt."""
    lines: list[str] = []
    for agent in AGENT_REGISTRY.values():
        lines.append(f'- "{agent.name}": {agent.description}')
    return "\n".join(lines)
