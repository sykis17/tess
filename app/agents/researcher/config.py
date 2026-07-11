from app.agents.researcher.prompt import RESEARCHER_SYSTEM_PROMPT
from app.agents.schemas import AgentConfig

RESEARCHER_CONFIG = AgentConfig(
    name="researcher",
    folder_path="Research/Topics",
    description=(
        "Handles factual research, explanations, summaries, and educational "
        "questions such as what something is or how it works."
    ),
    system_prompt=RESEARCHER_SYSTEM_PROMPT,
)
