"""Phase 20 token streaming utility tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest

from app.graph.schemas import Panel
from app.graph.stream_utils import generate_with_panel_stream
from app.llm.types import LLMMessage


class _FakeLLM:
    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks

    async def stream(self, request) -> AsyncIterator[str]:
        for chunk in self._chunks:
            yield chunk


def test_generate_with_panel_stream_assembles_full_text() -> None:
    panel = Panel(
        panel_id="p1",
        folder_path="Assistant/General",
        status="processing",
        content_type="markdown",
        content="",
    )
    llm = _FakeLLM(["Hello", " ", "world"])

    async def run() -> str:
        with patch("app.graph.stream_utils.is_session_interrupted", return_value=False):
            with patch("app.graph.stream_utils.publish_panel") as publish:
                result = await generate_with_panel_stream(
                llm=llm,
                messages=[LLMMessage(role="user", content="hi")],
                panel=panel,
                session_id="sess-1",
                throttle_ms=0,
                )
            assert publish.call_count >= 1
            for call in publish.call_args_list:
                published = call.args[0]
                assert published.is_streaming is True
            return result

    assert asyncio.run(run()) == "Hello world"


def test_generate_with_panel_stream_raises_on_interrupt() -> None:
    from app.core.session_control import SessionInterrupted

    panel = Panel(
        panel_id="p1",
        folder_path="Assistant/General",
        status="processing",
        content_type="markdown",
        content="",
    )
    llm = _FakeLLM(["one", "two", "three"])

    async def run() -> None:
        with patch("app.graph.stream_utils.is_session_interrupted", return_value=True):
            with patch("app.graph.stream_utils.publish_panel"):
                with pytest.raises(SessionInterrupted):
                    await generate_with_panel_stream(
                        llm=llm,
                        messages=[LLMMessage(role="user", content="hi")],
                        panel=panel,
                        session_id="sess-1",
                        throttle_ms=0,
                    )

    asyncio.run(run())


def test_generate_with_panel_stream_batches_by_throttle() -> None:
    panel = Panel(
        panel_id="p1",
        folder_path="Assistant/General",
        status="processing",
        content_type="markdown",
        content="",
    )
    llm = _FakeLLM(["a", "b", "c"])

    async def run() -> tuple[str, int]:
        with patch("app.graph.stream_utils.is_session_interrupted", return_value=False):
            with patch("app.graph.stream_utils.publish_panel") as publish:
                with patch("app.graph.stream_utils.time.monotonic") as monotonic:
                    monotonic.side_effect = [0.0, 0.0, 0.2, 0.2, 0.2, 0.2]
                    result = await generate_with_panel_stream(
                        llm=llm,
                        messages=[LLMMessage(role="user", content="hi")],
                        panel=panel,
                        session_id="sess-1",
                        throttle_ms=100,
                    )
            return result, publish.call_count

    result, call_count = asyncio.run(run())
    assert result == "abc"
    assert call_count == 2
