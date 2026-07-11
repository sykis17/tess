from app.agents.general_assistant.prompt import GENERAL_ASSISTANT_SYSTEM_PROMPT
from app.agents.schemas import AgentConfig

GENERAL_ASSISTANT_CONFIG = AgentConfig(
    name="general_assistant",
    folder_path="Assistant/General",
    description=(
        "Handles general questions, explanations, brainstorming, summaries, "
        "and everyday conversational tasks."
    ),
    system_prompt=GENERAL_ASSISTANT_SYSTEM_PROMPT,
)
