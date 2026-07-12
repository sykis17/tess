from app.agents.art.prompt import ART_POV_SYSTEM_PROMPT
from app.agents.schemas import AgentConfig

ART_CONFIG = AgentConfig(
    name="art",
    folder_path="Arts/Visual",
    description=(
        "Art POV — composition, color, style, visual hierarchy, "
        "and aesthetic reasoning from an art lens."
    ),
    system_prompt=ART_POV_SYSTEM_PROMPT,
    pov="Art",
    agent_kind="pov",
)
