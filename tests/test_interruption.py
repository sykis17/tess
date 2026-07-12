"""Phase 20 worker interruption handling."""

import asyncio
from unittest.mock import MagicMock, patch

from app.worker import _run_graph_with_streaming


def test_run_graph_stops_when_session_interrupted() -> None:
    initial_state = {
        "session_id": "sess-int",
        "panel_id": "panel-1",
        "user_input": "test",
    }
    redis_client = MagicMock()

    async def fake_astream(state, stream_mode):
        yield {"wide_receiver": {"panels": []}}
        yield {"presenter": {"panels": []}}

    mock_graph = MagicMock()
    mock_graph.astream = fake_astream

    async def run():
        with patch("app.worker.compiled_graph", mock_graph):
            with patch("app.worker.is_session_interrupted", side_effect=[False, True]):
                with patch("app.worker._publish_cancelled") as publish_cancelled:
                    result = await _run_graph_with_streaming(
                        initial_state,
                        redis_client,
                        "channel_sess-int",
                        "sess-int",
                    )
        publish_cancelled.assert_called_once()
        return result

    result = asyncio.run(run())
    assert result["session_id"] == "sess-int"
