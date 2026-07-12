from app.agents.biology_minor.prompt import BIOLOGY_MINOR_SYSTEM_PROMPT
from app.agents.schemas import AgentConfig

BIOLOGY_MINOR_CONFIG = AgentConfig(
    name="biology_minor",
    folder_path="Science/Biology",
    description=(
        "Biology — brief overviews and simple explanations of living systems, cells, "
        "and life-science concepts."
    ),
    system_prompt=BIOLOGY_MINOR_SYSTEM_PROMPT,
    subject="Biology",
    depth="minor",
    agent_kind="topic",
)
