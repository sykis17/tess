from typing import Literal

from pydantic import BaseModel, Field

PanelStatus = Literal["processing", "review_passed", "completed"]
ContentType = Literal["markdown", "code", "image", "audio", "video"]
ContentFormat = Literal["markdown", "ranked_list"]
DataTier = Literal["mayor", "micro", "usable", "final"]
ReviewStatus = Literal["pending", "approved", "revise"]
CheckVerdict = Literal["pass", "revise"]
DefenseVerdict = Literal["pass", "revise", "reject"]

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
    """Raw output from a POV or specialist agent before combiner stages."""

    source_agent: str
    content: str
    topic: str | None = None
    pov: str | None = None
    citations: list[str] = Field(default_factory=list)


class MicroDataSegment(BaseModel):
    """A sorted catalog entry from Combiner Mayor — one theme or POV slice."""

    title: str
    content: str
    source_agents: list[str] = Field(default_factory=list)
    overlap_notes: str | None = None


class MicroData(BaseModel):
    """Combiner Mayor output — sorted inventory with overlap annotations."""

    combiner: Literal["mayor"] = "mayor"
    segments: list[MicroDataSegment]
    source_agents: list[str] = Field(default_factory=list)


class UsableAnswer(BaseModel):
    """Combiner Micro output — deduplicated segment ready for collection."""

    segment_id: str
    order_hint: int
    title: str
    content: str
    review_status: ReviewStatus = "pending"
    source_agents: list[str] = Field(default_factory=list)


class DefenseChecks(BaseModel):
    """Per-segment QA check results from Defense Review."""

    big_picture: CheckVerdict
    detail: CheckVerdict
    implication: CheckVerdict


class DefenseReview(BaseModel):
    """Defense QA verdict for a single answer segment."""

    segment_id: str
    checks: DefenseChecks
    notes: str = ""
    verdict: DefenseVerdict


class PanelSegment(BaseModel):
    """Structured per-lens section on a completed Panel."""

    title: str
    content: str
    source_agents: list[str] = Field(default_factory=list)
    pov: str | None = None


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
    pov_sources: list[str] = Field(default_factory=list)
    product_mode: str | None = None
    output_level: str | None = None
    pipeline_stage: str | None = None
    pov_segments: list[PanelSegment] = Field(default_factory=list)
    content_format: ContentFormat | None = None
    follow_up_kinds: list[str] = Field(default_factory=list)
    is_streaming: bool = False
