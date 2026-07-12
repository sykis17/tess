"""Phase 20 session control Redis helpers."""

from unittest.mock import MagicMock, patch

from app.core import session_control


def test_set_and_get_active_task() -> None:
    mock_client = MagicMock()
    with patch("app.core.session_control.create_sync_redis", return_value=mock_client):
        session_control.set_active_task("sess-1", "task-abc")
        mock_client.set.assert_called_once_with(
            "session:sess-1:active_task",
            "task-abc",
            ex=session_control.SESSION_KEY_TTL_SECONDS,
        )
        mock_client.close.assert_called_once()

        mock_client.get.return_value = "task-abc"
        assert session_control.get_active_task("sess-1") == "task-abc"


def test_interrupt_flag_round_trip() -> None:
    mock_client = MagicMock()
    with patch("app.core.session_control.create_sync_redis", return_value=mock_client):
        session_control.set_interrupt("sess-2")
        mock_client.set.assert_called_with(
            "session:sess-2:interrupt",
            "1",
            ex=session_control.SESSION_KEY_TTL_SECONDS,
        )

        mock_client.get.return_value = "1"
        assert session_control.is_session_interrupted("sess-2") is True

        session_control.clear_interrupt("sess-2")
        mock_client.delete.assert_called_with("session:sess-2:interrupt")


def test_clear_active_task_if_matches() -> None:
    mock_client = MagicMock()
    with patch("app.core.session_control.create_sync_redis", return_value=mock_client):
        mock_client.get.return_value = "task-1"
        session_control.clear_active_task_if_matches("sess-3", "task-1")
        mock_client.delete.assert_called_with("session:sess-3:active_task")

        mock_client.reset_mock()
        mock_client.get.return_value = "task-other"
        session_control.clear_active_task_if_matches("sess-3", "task-1")
        mock_client.delete.assert_not_called()


def test_revoke_active_task() -> None:
    mock_client = MagicMock()
    mock_celery = MagicMock()
    with patch("app.core.session_control.create_sync_redis", return_value=mock_client):
        with patch("app.core.session_control.get_active_task", return_value="task-99"):
            with patch("app.worker.celery_app", mock_celery):
                session_control.revoke_active_task("sess-4")

    mock_celery.control.revoke.assert_called_once_with("task-99", terminate=True)
