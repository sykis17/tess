from app.agents.coder.prompt import CODER_SYSTEM_PROMPT
from app.agents.schemas import AgentConfig

CODER_CONFIG = AgentConfig(
    name="coder",
    folder_path="Coding/Projects",
    description=(
        "Handles code generation, debugging, refactoring, technical implementation, "
        "and software development questions."
    ),
    system_prompt=CODER_SYSTEM_PROMPT,
    agent_kind="tool",
)
