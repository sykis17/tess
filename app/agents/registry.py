from app.agents.art.config import ART_CONFIG
from app.agents.audio.config import AUDIO_CONFIG
from app.agents.biology.config import BIOLOGY_CONFIG
from app.agents.chemistry.config import CHEMISTRY_CONFIG
from app.agents.coder.config import CODER_CONFIG
from app.agents.economics.config import ECONOMICS_CONFIG
from app.agents.general_assistant.config import GENERAL_ASSISTANT_CONFIG
from app.agents.photo.config import PHOTO_CONFIG
from app.agents.researcher.config import RESEARCHER_CONFIG
from app.agents.schemas import AgentConfig
from app.agents.ui_design.config import UI_DESIGN_CONFIG
from app.agents.video.config import VIDEO_CONFIG

AGENT_REGISTRY: dict[str, AgentConfig] = {
    GENERAL_ASSISTANT_CONFIG.name: GENERAL_ASSISTANT_CONFIG,
    CODER_CONFIG.name: CODER_CONFIG,
    RESEARCHER_CONFIG.name: RESEARCHER_CONFIG,
    PHOTO_CONFIG.name: PHOTO_CONFIG,
    VIDEO_CONFIG.name: VIDEO_CONFIG,
    AUDIO_CONFIG.name: AUDIO_CONFIG,
    CHEMISTRY_CONFIG.name: CHEMISTRY_CONFIG,
    BIOLOGY_CONFIG.name: BIOLOGY_CONFIG,
    ECONOMICS_CONFIG.name: ECONOMICS_CONFIG,
    ART_CONFIG.name: ART_CONFIG,
    UI_DESIGN_CONFIG.name: UI_DESIGN_CONFIG,
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
    "chemistry": "Chemistry",
    "biology": "Biology",
    "economics": "Economics",
    "art": "Art",
    "ui_design": "UI Design",
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
        if agent.pov:
            return agent.pov

    return registry_key.replace("_", " ").title()


def list_agents_for_prompt() -> str:
    """Format registered agents for inclusion in the Wide Receiver routing prompt."""
    lines: list[str] = []
    for agent in AGENT_REGISTRY.values():
        lines.append(f'- "{agent.name}": {agent.description}')
    return "\n".join(lines)


def list_pov_agents_for_prompt() -> str:
    """Format POV agents for the Wide Receiver routing prompt."""
    lines: list[str] = []
    for agent in AGENT_REGISTRY.values():
        if agent.agent_kind == "pov":
            lines.append(f'- "{agent.name}": {agent.description}')
    return "\n".join(lines)


def list_tool_agents_for_prompt() -> str:
    """Format tool and media agents for the Wide Receiver routing prompt."""
    lines: list[str] = []
    for agent in AGENT_REGISTRY.values():
        if agent.agent_kind in {"tool", "media"}:
            lines.append(f'- "{agent.name}": {agent.description}')
    return "\n".join(lines)
