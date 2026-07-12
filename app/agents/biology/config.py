from app.agents.biology.prompt import BIOLOGY_POV_SYSTEM_PROMPT
from app.agents.schemas import AgentConfig

BIOLOGY_CONFIG = AgentConfig(
    name="biology",
    folder_path="Science/Biology",
    description=(
        "Biology POV — cells, ecosystems, physiology, genetics, "
        "and life-science reasoning from a biology lens."
    ),
    system_prompt=BIOLOGY_POV_SYSTEM_PROMPT,
    pov="Biology",
    agent_kind="pov",
)
