from app.llm.types import LLMMessage


def conversation_turn_count(history: list[LLMMessage]) -> int:
    """Return the number of conversation turns in a message history."""
    return len(history) // 2


def format_history_input(turn_count: int) -> str:
    """Format conversation history as an inputs_seen label."""
    if turn_count == 0:
        return "conversation_history (none)"
    label = "turn" if turn_count == 1 else "turns"
    return f"conversation_history ({turn_count} {label})"


def truncate_preview(text: str, max_chars: int = 200) -> str:
    """Truncate text for agent trace output previews."""
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    return f"{stripped[:max_chars].rstrip()}…"
