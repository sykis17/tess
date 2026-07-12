from app.agents.biology_major.prompt import BIOLOGY_MAJOR_SYSTEM_PROMPT
from app.agents.schemas import AgentConfig

BIOLOGY_MAJOR_CONFIG = AgentConfig(
    name="biology_major",
    folder_path="Science/Biology",
    description=(
        "Biology — in-depth explanations of cells, genetics, ecosystems, evolution, "
        "and detailed life-science reasoning."
    ),
    system_prompt=BIOLOGY_MAJOR_SYSTEM_PROMPT,
    subject="Biology",
    depth="major",
    agent_kind="topic",
)
