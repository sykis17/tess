"""Phase 20 progress heartbeat during blocking LLM calls."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.core.session_control import SessionInterrupted
from app.graph.progress_utils import generate_with_progress_heartbeat, _format_elapsed
from app.graph.schemas import Panel
from app.llm.types import LLMMessage, LLMResponse


class _SlowLLM:
    def __init__(self, content: str = "result", delay: float = 0.2) -> None:
        self._content = content
        self._delay = delay
        self.provider = MagicMock(value="ollama")

    async def generate(self, request) -> LLMResponse:
        await asyncio.sleep(self._delay)
        return LLMResponse(content=self._content, provider="ollama", model="test")


def test_format_elapsed() -> None:
    assert _format_elapsed(45) == "45s"
    assert _format_elapsed(125) == "2m 5s"


def test_generate_with_progress_heartbeat_returns_content() -> None:
    panel = Panel(
        panel_id="p1",
        folder_path="Design/UI",
        status="processing",
        content_type="markdown",
        content="Starting…",
    )
    llm = _SlowLLM(content='{"segments": []}', delay=0.05)

    async def run() -> str:
        with patch("app.graph.progress_utils.publish_panel") as publish:
            with patch("app.graph.progress_utils.is_session_interrupted", return_value=False):
                result = await generate_with_progress_heartbeat(
                    llm=llm,
                    messages=[LLMMessage(role="user", content="combine")],
                    panel=panel,
                    session_id="sess-1",
                    working_label="Combiner Mayor working",
                    heartbeat_seconds=0.01,
                )
        assert publish.call_count >= 1
        return result

    assert asyncio.run(run()) == '{"segments": []}'


def test_generate_with_progress_heartbeat_raises_on_interrupt() -> None:
    panel = Panel(
        panel_id="p1",
        folder_path="Design/UI",
        status="processing",
        content_type="markdown",
        content="Starting…",
    )
    llm = _SlowLLM(delay=2.0)

    async def run() -> None:
        with patch("app.graph.progress_utils.publish_panel"):
            with patch(
                "app.graph.progress_utils.is_session_interrupted",
                side_effect=[False, True],
            ):
                with pytest.raises(SessionInterrupted):
                    await generate_with_progress_heartbeat(
                        llm=llm,
                        messages=[LLMMessage(role="user", content="combine")],
                        panel=panel,
                        session_id="sess-1",
                        working_label="Combiner Mayor working",
                        heartbeat_seconds=0.01,
                    )

    asyncio.run(run())
