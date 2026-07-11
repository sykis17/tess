from app.agents.general_assistant.prompt import GENERAL_ASSISTANT_SYSTEM_PROMPT
from app.agents.schemas import AgentConfig

GENERAL_ASSISTANT_CONFIG = AgentConfig(
    name="general_assistant",
    folder_path="Assistant/General",
    description=(
        "Handles casual conversation, brainstorming, and general tasks that do not "
        "require dedicated coding or research specialists."
    ),
    system_prompt=GENERAL_ASSISTANT_SYSTEM_PROMPT,
)
