import logging
from typing import Any

from app.agents.registry import DEFAULT_AGENT_NAME, get_agent
from app.agents.subjects.registry import collect_pov_sources
from app.graph.defense_utils import (
    aggregate_defense_notes,
    apply_defense_verdicts,
    build_agents_involved_with_defense,
    format_defense_trace_preview,
    format_review_passed_content,
    parse_defense_reviews_json,
    serialize_segments_for_llm,
)
from app.graph.panel_stream import publish_panel
from app.graph.pipeline_stages import PipelineStage
from app.graph.progress_utils import generate_with_progress_heartbeat
from app.graph.prompts import build_defense_prompt
from app.graph.schemas import AgentTrace, Panel
from app.graph.state import GraphState
from app.llm.factory import create_llm
from app.llm.types import LLMMessage

logger = logging.getLogger(__name__)


def _resolve_folder_path(state: GraphState) -> str:
    active_agents = state.get("active_agents") or []
    agent_name = active_agents[0] if active_agents else DEFAULT_AGENT_NAME
    try:
        return get_agent(agent_name).folder_path
    except KeyError:
        return get_agent(DEFAULT_AGENT_NAME).folder_path


async def defense_review_node(state: GraphState) -> dict[str, Any]:
    """Run QA checks on answer segments and emit a review_passed Panel."""
    segments = state.get("usable_answers") or []
    current_task = state.get("current_task") or state["user_input"]
    defense_notes = (state.get("defense_notes") or "").strip()
    combiners_bypassed = state.get("combiners_bypassed", True)

    if not segments:
        logger.warning("Defense Review: no segments to review")
        trace = AgentTrace(
            agent_name="defense_review",
            inputs_seen=[],
            task_summary=current_task,
            output_preview="No segments to review.",
        )
        return {"agent_traces": [trace], "defense_reviews": []}

    segments_text = serialize_segments_for_llm(segments)
    user_parts = [f"Task: {current_task}", f"\nSegments to review:\n\n{segments_text}"]
    if defense_notes:
        user_parts.append(f"\nPrior revision notes (for context):\n{defense_notes}")

    product_mode = state.get("product_mode", "auto")
    messages: list[LLMMessage] = [
        LLMMessage(role="system", content=build_defense_prompt(product_mode)),
        LLMMessage(role="user", content="\n".join(user_parts)),
    ]

    session_id = state.get("session_id", "")
    pov_sources = collect_pov_sources(state.get("active_agents") or [])
    include_combiners = not combiners_bypassed and bool(segments)
    progress_panel = Panel(
        panel_id=state["panel_id"],
        folder_path=_resolve_folder_path(state),
        status="processing",
        content_type="markdown",
        content=f"Reviewing {len(segments)} answer segment(s)…",
        follow_up_options=[],
        agents_involved=build_agents_involved_with_defense(
            state,
            include_combiners=include_combiners,
        ),
        agent_traces=state.get("agent_traces", []),
        data_tier="usable",
        pov_sources=pov_sources,
        output_level=state.get("chain_profile"),
        pipeline_stage=PipelineStage.DEFENSE,
    )
    if session_id:
        publish_panel(progress_panel, session_id)

    llm = create_llm()
    response_content = await generate_with_progress_heartbeat(
        llm=llm,
        messages=messages,
        panel=progress_panel,
        session_id=session_id,
        working_label="**Defense Review** — checking quality and accuracy",
    )
    reviews = parse_defense_reviews_json(response_content, segments)
    updated_segments = apply_defense_verdicts(segments, reviews)
    notes = aggregate_defense_notes(reviews)

    logger.info(
        "Defense Review completed via %s; segments=%d passed=%d",
        llm.provider.value,
        len(reviews),
        sum(1 for review in reviews if review.verdict == "pass"),
    )

    trace = AgentTrace(
        agent_name="defense_review",
        inputs_seen=[
            f"segments ({len(segments)})",
            f"defense_retry_count ({state.get('defense_retry_count') or 0})",
        ],
        task_summary=current_task,
        output_preview=format_defense_trace_preview(reviews),
    )

    review_panel = Panel(
        panel_id=state["panel_id"],
        folder_path=_resolve_folder_path(state),
        status="review_passed",
        content_type="markdown",
        content=format_review_passed_content(reviews),
        follow_up_options=[],
        agents_involved=build_agents_involved_with_defense(
            state,
            include_combiners=include_combiners,
        ),
        agent_traces=[*state.get("agent_traces", []), trace],
        data_tier="usable",
        pov_sources=collect_pov_sources(state.get("active_agents") or []),
        output_level=state.get("chain_profile"),
        pipeline_stage=PipelineStage.DEFENSE,
    )

    return {
        "defense_reviews": reviews,
        "usable_answers": updated_segments,
        "defense_notes": notes,
        "agent_traces": [trace],
        "panels": [review_panel],
    }
