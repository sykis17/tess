"""Progress feedback during long blocking LLM calls (combiners, defense, routing)."""

from __future__ import annotations

import asyncio
import time

from app.core.config import settings
from app.core.session_control import SessionInterrupted, is_session_interrupted
from app.graph.panel_stream import publish_panel
from app.graph.schemas import Panel
from app.llm.base import BaseLLM
from app.llm.types import LLMMessage, LLMRequest


def _format_elapsed(seconds: int) -> str:
    minutes, secs = divmod(seconds, 60)
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


async def generate_with_progress_heartbeat(
    *,
    llm: BaseLLM,
    messages: list[LLMMessage],
    panel: Panel,
    session_id: str,
    working_label: str,
    heartbeat_seconds: float | None = None,
) -> str:
    """Run a blocking LLM call with periodic progress Panel updates."""
    request = LLMRequest(messages=messages)

    if not session_id:
        response = await llm.generate(request)
        return response.content

    if heartbeat_seconds is None:
        heartbeat_seconds = settings.progress_heartbeat_seconds

    start = time.monotonic()
    last_publish = start - heartbeat_seconds

    generate_task = asyncio.create_task(llm.generate(request))

    publish_panel(
        panel.model_copy(
            update={
                "content": f"{working_label} *(starting)*",
                "is_streaming": False,
            }
        ),
        session_id,
    )

    try:
        while not generate_task.done():
            if is_session_interrupted(session_id):
                generate_task.cancel()
                raise SessionInterrupted()

            elapsed = time.monotonic() - start
            if elapsed - last_publish >= heartbeat_seconds:
                elapsed_int = int(elapsed)
                publish_panel(
                    panel.model_copy(
                        update={
                            "content": (
                                f"{working_label} *(running {_format_elapsed(elapsed_int)})*"
                            ),
                            "is_streaming": False,
                        }
                    ),
                    session_id,
                )
                last_publish = elapsed

            await asyncio.sleep(0.5)

        return generate_task.result().content
    except asyncio.CancelledError:
        raise SessionInterrupted() from None
