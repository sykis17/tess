from app.agents.chemistry_major.prompt import CHEMISTRY_MAJOR_SYSTEM_PROMPT
from app.agents.schemas import AgentConfig

CHEMISTRY_MAJOR_CONFIG = AgentConfig(
    name="chemistry_major",
    folder_path="Science/Chemistry",
    description=(
        "Chemistry — in-depth explanations, lab concepts, bonding, reactions, "
        "stoichiometry, and detailed scientific reasoning."
    ),
    system_prompt=CHEMISTRY_MAJOR_SYSTEM_PROMPT,
    subject="Chemistry",
    depth="major",
    agent_kind="topic",
)
