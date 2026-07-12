from app.agents.chemistry_minor.prompt import CHEMISTRY_MINOR_SYSTEM_PROMPT
from app.agents.schemas import AgentConfig

CHEMISTRY_MINOR_CONFIG = AgentConfig(
    name="chemistry_minor",
    folder_path="Science/Chemistry",
    description=(
        "Chemistry — brief overviews and simple explanations of chemical concepts, "
        "bonding, and reactions."
    ),
    system_prompt=CHEMISTRY_MINOR_SYSTEM_PROMPT,
    subject="Chemistry",
    depth="minor",
    agent_kind="topic",
)
