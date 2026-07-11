from typing import Literal

from pydantic import BaseModel, Field

PanelStatus = Literal["processing", "review_passed", "completed"]
ContentType = Literal["markdown", "code", "image"]

DEFAULT_FOLLOW_UP_OPTIONS: list[str] = [
    "Continue with this",
    "Change style",
    "Discard",
]


class Panel(BaseModel):
    """WebSocket payload streamed to the frontend when a processing segment completes."""

    panel_id: str
    folder_path: str
    status: PanelStatus
    content_type: ContentType
    content: str
    follow_up_options: list[str] = Field(default_factory=lambda: list(DEFAULT_FOLLOW_UP_OPTIONS))
