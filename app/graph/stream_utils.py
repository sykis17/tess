"""Token streaming helpers for partial Panel delivery."""

from __future__ import annotations

import time

from app.core.config import settings
from app.core.session_control import SessionInterrupted, is_session_interrupted
from app.graph.panel_stream import publish_panel
from app.graph.schemas import Panel
from app.llm.base import BaseLLM
from app.llm.types import LLMMessage, LLMRequest


async def generate_with_panel_stream(
    *,
    llm: BaseLLM,
    messages: list[LLMMessage],
    panel: Panel,
    session_id: str,
    throttle_ms: int | None = None,
) -> str:
    """Stream LLM tokens, publish batched partial Panels, return full text."""
    if throttle_ms is None:
        throttle_ms = settings.stream_throttle_ms

    full_parts: list[str] = []
    buffer: list[str] = []
    last_publish = time.monotonic()

    request = LLMRequest(messages=messages)

    async for chunk in llm.stream(request):
        if is_session_interrupted(session_id):
            raise SessionInterrupted()

        full_parts.append(chunk)
        buffer.append(chunk)

        elapsed_ms = (time.monotonic() - last_publish) * 1000
        if elapsed_ms >= throttle_ms and buffer:
            delta = "".join(buffer)
            buffer.clear()
            last_publish = time.monotonic()
            publish_panel(
                panel.model_copy(update={"content": delta, "is_streaming": True}),
                session_id,
            )

    if buffer:
        delta = "".join(buffer)
        publish_panel(
            panel.model_copy(update={"content": delta, "is_streaming": True}),
            session_id,
        )

    return "".join(full_parts)
