import json
import logging

from app.core.redis import create_sync_redis
from app.llm.types import LLMMessage

logger = logging.getLogger(__name__)

MAX_CONVERSATION_MESSAGES = 20
CONVERSATION_KEY_PREFIX = "conversation:"


def _conversation_key(session_id: str) -> str:
    return f"{CONVERSATION_KEY_PREFIX}{session_id}"


def _trim_history(messages: list[LLMMessage]) -> list[LLMMessage]:
    """Keep the most recent messages within the configured cap."""
    if len(messages) <= MAX_CONVERSATION_MESSAGES:
        return messages
    return messages[-MAX_CONVERSATION_MESSAGES:]


def load_conversation_history(session_id: str) -> list[LLMMessage]:
    """Load prior conversation turns for a session from Redis."""
    redis_client = create_sync_redis()
    try:
        raw = redis_client.get(_conversation_key(session_id))
        if not raw:
            return []

        data = json.loads(raw)
        return [LLMMessage.model_validate(entry) for entry in data]
    except (json.JSONDecodeError, ValueError):
        logger.warning("Invalid conversation history for session %s; resetting.", session_id)
        return []
    finally:
        redis_client.close()


def save_conversation_history(session_id: str, messages: list[LLMMessage]) -> None:
    """Persist conversation turns for a session to Redis."""
    trimmed = _trim_history(messages)
    redis_client = create_sync_redis()
    try:
        payload = json.dumps([message.model_dump() for message in trimmed])
        redis_client.set(_conversation_key(session_id), payload)
    finally:
        redis_client.close()


def append_conversation_turn(
    session_id: str,
    user_input: str,
    assistant_response: str,
) -> list[LLMMessage]:
    """Append a user/assistant turn and persist the updated history."""
    history = load_conversation_history(session_id)
    history.extend(
        [
            LLMMessage(role="user", content=user_input),
            LLMMessage(role="assistant", content=assistant_response),
        ]
    )
    save_conversation_history(session_id, history)
    return history
