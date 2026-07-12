from app.agents.audio.config import AUDIO_CONFIG
from app.agents.biology_major.config import BIOLOGY_MAJOR_CONFIG
from app.agents.biology_minor.config import BIOLOGY_MINOR_CONFIG
from app.agents.chemistry_major.config import CHEMISTRY_MAJOR_CONFIG
from app.agents.chemistry_minor.config import CHEMISTRY_MINOR_CONFIG
from app.agents.coder.config import CODER_CONFIG
from app.agents.economics_major.config import ECONOMICS_MAJOR_CONFIG
from app.agents.economics_minor.config import ECONOMICS_MINOR_CONFIG
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
    CHEMISTRY_MAJOR_CONFIG.name: CHEMISTRY_MAJOR_CONFIG,
    CHEMISTRY_MINOR_CONFIG.name: CHEMISTRY_MINOR_CONFIG,
    BIOLOGY_MAJOR_CONFIG.name: BIOLOGY_MAJOR_CONFIG,
    BIOLOGY_MINOR_CONFIG.name: BIOLOGY_MINOR_CONFIG,
    ECONOMICS_MAJOR_CONFIG.name: ECONOMICS_MAJOR_CONFIG,
    ECONOMICS_MINOR_CONFIG.name: ECONOMICS_MINOR_CONFIG,
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
    "chemistry_major": "Chemistry Major",
    "chemistry_minor": "Chemistry Minor",
    "biology_major": "Biology Major",
    "biology_minor": "Biology Minor",
    "economics_major": "Economics Major",
    "economics_minor": "Economics Minor",
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
        agent = AGENT_REGISTRY[registry_key]
        if agent.subject and agent.depth:
            depth_label = agent.depth.title()
            return f"{agent.subject} {depth_label}"

    return registry_key.replace("_", " ").title()


def list_agents_for_prompt() -> str:
    """Format registered agents for inclusion in the Wide Receiver routing prompt."""
    lines: list[str] = []
    for agent in AGENT_REGISTRY.values():
        lines.append(f'- "{agent.name}": {agent.description}')
    return "\n".join(lines)


def list_topic_agents_for_prompt() -> str:
    """Format topic agents for the Wide Receiver routing prompt."""
    lines: list[str] = []
    for agent in AGENT_REGISTRY.values():
        if agent.agent_kind == "topic":
            lines.append(f'- "{agent.name}": {agent.description}')
    return "\n".join(lines)


def list_tool_agents_for_prompt() -> str:
    """Format tool and media agents for the Wide Receiver routing prompt."""
    lines: list[str] = []
    for agent in AGENT_REGISTRY.values():
        if agent.agent_kind in {"tool", "media"}:
            lines.append(f'- "{agent.name}": {agent.description}')
    return "\n".join(lines)
