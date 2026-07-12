from app.agents.schemas import AgentConfig
from app.agents.ui_design.prompt import UI_DESIGN_POV_SYSTEM_PROMPT

UI_DESIGN_CONFIG = AgentConfig(
    name="ui_design",
    folder_path="Design/UI",
    description=(
        "UI Design POV — layout, usability, patterns, navigation, "
        "and interaction reasoning from a UX/interface lens."
    ),
    system_prompt=UI_DESIGN_POV_SYSTEM_PROMPT,
    pov="UI Design",
    agent_kind="pov",
)
