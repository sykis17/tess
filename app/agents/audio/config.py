from app.agents.audio.prompt import AUDIO_SYSTEM_PROMPT
from app.agents.schemas import AgentConfig

AUDIO_CONFIG = AgentConfig(
    name="audio",
    folder_path="Media/Audio",
    description=(
        "Handles voiceover scripts, podcast outlines, episode structures, "
        "narration drafts, and audio metadata plans."
    ),
    system_prompt=AUDIO_SYSTEM_PROMPT,
    agent_kind="media",
)
