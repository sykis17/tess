from typing import Literal

from pydantic import BaseModel, Field

PanelStatus = Literal["processing", "review_passed", "completed"]
ContentType = Literal["markdown", "code", "image"]
DataTier = Literal["mayor", "micro", "usable", "final"]
ReviewStatus = Literal["pending", "approved", "revise"]

DEFAULT_FOLLOW_UP_OPTIONS: list[str] = [
    "Continue with this",
    "Change style",
    "Discard",
]

OUTPUT_PREVIEW_MAX_CHARS = 200


class AgentTrace(BaseModel):
    """Per-agent visibility record for what an agent saw and produced."""

    agent_name: str
    inputs_seen: list[str]
    task_summary: str | None = None
    output_preview: str | None = None


class SearchResult(BaseModel):
    """A single search hit with extracted excerpt from resource reader."""

    query: str
    url: str
    title: str
    excerpt: str = ""
    reader_agent: str = "resource_reader"


class MayorData(BaseModel):
    """Raw output from a topic agent before combiner stages."""

    source_agent: str
    content: str
    topic: str | None = None
    depth: str | None = None
    citations: list[str] = Field(default_factory=list)


class MicroDataSegment(BaseModel):
    """A single cross-topic synthesis segment from Combiner Mayor."""

    title: str
    content: str


class MicroData(BaseModel):
    """Combiner Mayor output — cross-topic synthesis across mayor data."""

    combiner: Literal["mayor"] = "mayor"
    segments: list[MicroDataSegment]
    source_agents: list[str] = Field(default_factory=list)


class UsableAnswer(BaseModel):
    """Combiner Micro output — refined segment ready for collection."""

    segment_id: str
    order_hint: int
    title: str
    content: str
    review_status: ReviewStatus = "pending"


class Panel(BaseModel):
    """WebSocket payload streamed to the frontend when a processing segment completes."""

    panel_id: str
    folder_path: str
    status: PanelStatus
    content_type: ContentType
    content: str
    follow_up_options: list[str] = Field(default_factory=lambda: list(DEFAULT_FOLLOW_UP_OPTIONS))
    agents_involved: list[str] = Field(default_factory=list)
    agent_traces: list[AgentTrace] = Field(default_factory=list)
    data_tier: DataTier | None = None
