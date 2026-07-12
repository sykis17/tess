from app.agents.photo.prompt import PHOTO_SYSTEM_PROMPT
from app.agents.schemas import AgentConfig

PHOTO_CONFIG = AgentConfig(
    name="photo",
    folder_path="Media/Photo",
    description=(
        "Handles diagram plans, image descriptions, visual layouts, icons, "
        "illustration specs, and image composition guidance."
    ),
    system_prompt=PHOTO_SYSTEM_PROMPT,
)
