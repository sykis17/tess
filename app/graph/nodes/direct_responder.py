import logging
from typing import Any

from app.agents.registry import DEFAULT_AGENT_NAME, get_agent
from app.core.session_control import SessionInterrupted
from app.graph.panel_stream import publish_panel
from app.graph.pipeline_stages import PipelineStage
from app.graph.schemas import AgentTrace, MayorData, Panel
from app.graph.state import GraphState
from app.graph.stream_utils import generate_with_panel_stream
from app.graph.trace_utils import conversation_turn_count, format_history_input, truncate_preview
from app.llm.factory import create_llm
from app.llm.types import LLMMessage

logger = logging.getLogger(__name__)

DIRECT_RESPONDER_SYSTEM_PROMPT = (
    "You are a direct-response assistant in the TESS Engine (L0 chain profile).\n"
    "Answer the user's message clearly and concisely using conversation context.\n"
    "Use markdown when helpful. Do not mention internal routing or pipeline stages."
)


def _resolve_folder_path() -> str:
    return get_agent(DEFAULT_AGENT_NAME).folder_path


async def direct_responder_node(state: GraphState) -> dict[str, Any]:
    """L0 path — single LLM call without Wide Receiver or specialists."""
    user_input = state["user_input"]
    conversation_history = state["conversation_history"]
    chain_profile = state.get("chain_profile", "L0")
    session_id = state.get("session_id", "")
    turn_count = conversation_turn_count(conversation_history)

    logger.info("Direct responder handling L0 input: %s", user_input[:80])

    messages: list[LLMMessage] = [
        LLMMessage(role="system", content=DIRECT_RESPONDER_SYSTEM_PROMPT),
        *conversation_history,
        LLMMessage(role="user", content=user_input),
    ]

    streaming_panel = Panel(
        panel_id=state["panel_id"],
        folder_path=_resolve_folder_path(),
        status="processing",
        content_type="markdown",
        content="",
        follow_up_options=[],
        agents_involved=["Direct Responder", "Presenter"],
        agent_traces=state.get("agent_traces", []),
        output_level=chain_profile,
        pipeline_stage=PipelineStage.PRESENTING,
    )

    if session_id:
        publish_panel(streaming_panel, session_id)

    llm = create_llm()
    try:
        response_content = await generate_with_panel_stream(
            llm=llm,
            messages=messages,
            panel=streaming_panel,
            session_id=session_id,
        )
    except SessionInterrupted:
        raise

    trace = AgentTrace(
        agent_name="direct_responder",
        inputs_seen=["user_input", format_history_input(turn_count)],
        task_summary=user_input[:120] if len(user_input) > 120 else user_input,
        output_preview=truncate_preview(response_content),
    )

    mayor_entry = MayorData(
        source_agent="direct_responder",
        content=response_content,
        topic=user_input[:80] if len(user_input) > 80 else user_input,
    )

    return {
        "current_task": user_input,
        "active_agents": [],
        "collected_data": [response_content],
        "mayor_data": [mayor_entry],
        "combiners_bypassed": True,
        "agent_traces": [trace],
    }
