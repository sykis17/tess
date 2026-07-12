import logging
from typing import Any

from app.agents.registry import get_agent
from app.core.session_control import SessionInterrupted
from app.graph.defense_utils import build_panel_agents_involved
from app.graph.fan_in_utils import fan_in_branch_complete
from app.graph.panel_stream import publish_panel
from app.graph.pipeline_stages import PipelineStage
from app.graph.schemas import AgentTrace, MayorData, OUTPUT_PREVIEW_MAX_CHARS, Panel
from app.graph.state import GraphState
from app.graph.stream_utils import generate_with_panel_stream
from app.graph.trace_utils import conversation_turn_count, format_history_input, truncate_preview
from app.llm.factory import create_llm
from app.llm.types import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)


def _build_specialist_user_message(state: GraphState) -> str:
    """Build the user message for a specialist from WR routing output."""
    current_task = state["current_task"].strip()
    user_input = state["user_input"].strip()
    defense_notes = (state.get("defense_notes") or "").strip()

    if not current_task or current_task == user_input:
        base_message = user_input
    else:
        base_message = f"Task: {current_task}\n\nOriginal request: {user_input}"

    if defense_notes:
        base_message += f"\n\nDefense revision notes (address these):\n{defense_notes}"

    return base_message


def _maybe_increment_defense_retry(state: GraphState) -> int:
    """Increment defense retry count when re-entering after a failed review."""
    retry_count = state.get("defense_retry_count") or 0
    if (state.get("defense_notes") or "").strip():
        return retry_count + 1
    return retry_count


async def run_specialist(state: GraphState, agent_name: str) -> dict[str, Any]:
    """Execute a specialist agent LLM call and return collected data."""
    agent = get_agent(agent_name)
    conversation_history = state["conversation_history"]
    user_message = _build_specialist_user_message(state)
    turn_count = conversation_turn_count(conversation_history)

    logger.info("Specialist %s handling task: %s", agent_name, state["current_task"])

    session_id = state.get("session_id", "")
    streaming_panel: Panel | None = None
    if session_id:
        from app.agents.registry import DEFAULT_AGENT_NAME

        active_agents = state.get("active_agents") or []
        folder_agent = active_agents[0] if active_agents else DEFAULT_AGENT_NAME
        try:
            folder_path = get_agent(folder_agent).folder_path
        except KeyError:
            folder_path = get_agent(DEFAULT_AGENT_NAME).folder_path

        streaming_panel = Panel(
            panel_id=state["panel_id"],
            folder_path=folder_path,
            status="processing",
            content_type="markdown",
            content="",
            follow_up_options=[],
            agents_involved=build_panel_agents_involved(state, include_combiners=False),
            agent_traces=state.get("agent_traces", []),
            output_level=state.get("chain_profile"),
            pipeline_stage=PipelineStage.AGENTS,
        )
        publish_panel(streaming_panel, session_id)

    messages: list[LLMMessage] = [
        LLMMessage(role="system", content=agent.system_prompt),
        *conversation_history,
        LLMMessage(role="user", content=user_message),
    ]

    llm = create_llm()
    try:
        if streaming_panel is not None:
            response_content = await generate_with_panel_stream(
                llm=llm,
                messages=messages,
                panel=streaming_panel,
                session_id=session_id,
            )
        else:
            response = await llm.generate(LLMRequest(messages=messages))
            response_content = response.content
    except SessionInterrupted:
        raise

    logger.info("Specialist %s completed via streaming", agent_name)

    specialist_trace = AgentTrace(
        agent_name=agent_name,
        inputs_seen=[
            "user_input",
            "current_task",
            format_history_input(turn_count),
        ],
        task_summary=state["current_task"],
        output_preview=truncate_preview(response_content, OUTPUT_PREVIEW_MAX_CHARS),
    )

    mayor_entry = MayorData(
        source_agent=agent_name,
        content=response_content,
        topic=agent.pov or agent.description,
        pov=agent.pov,
    )

    result: dict[str, Any] = {
        "collected_data": [response_content],
        "mayor_data": [mayor_entry],
        "agent_traces": [specialist_trace],
        **fan_in_branch_complete(state, agent_name),
    }

    retry_count = _maybe_increment_defense_retry(state)
    if retry_count != (state.get("defense_retry_count") or 0):
        result["defense_retry_count"] = retry_count

    return result
