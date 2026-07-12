from app.agents.chemistry.prompt import CHEMISTRY_POV_SYSTEM_PROMPT
from app.agents.schemas import AgentConfig

CHEMISTRY_CONFIG = AgentConfig(
    name="chemistry",
    folder_path="Science/Chemistry",
    description=(
        "Chemistry POV — bonding, reactions, materials, stoichiometry, "
        "and scientific reasoning from a chemistry lens."
    ),
    system_prompt=CHEMISTRY_POV_SYSTEM_PROMPT,
    pov="Chemistry",
    agent_kind="pov",
)
