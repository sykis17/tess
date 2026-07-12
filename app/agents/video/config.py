from app.agents.schemas import AgentConfig
from app.agents.video.prompt import VIDEO_SYSTEM_PROMPT

VIDEO_CONFIG = AgentConfig(
    name="video",
    folder_path="Media/Video",
    description=(
        "Handles video scripts, storyboards, shot lists, edit plans, "
        "scene breakdowns, and narration timing."
    ),
    system_prompt=VIDEO_SYSTEM_PROMPT,
    agent_kind="media",
)
