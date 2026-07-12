"""Phase 19 — structured list format detection and markdown formatting."""

import re

_LIST_INTENT_PATTERNS = [
    re.compile(r"\btop\s+\d+\b", re.IGNORECASE),
    re.compile(r"\b\d+\s+best\b", re.IGNORECASE),
    re.compile(r"\bbest\s+\w+", re.IGNORECASE),
    re.compile(r"\blist\s+of\b", re.IGNORECASE),
    re.compile(r"\branked\b", re.IGNORECASE),
    re.compile(r"\btop\s+\w+\s+in\b", re.IGNORECASE),
]

_NUMBERED_LINE_PATTERN = re.compile(r"^\s*\d+\.\s+.+", re.MULTILINE)
_BULLET_LINE_PATTERN = re.compile(r"^\s*[-*]\s+(.+)$", re.MULTILINE)
_HEADING_PATTERN = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def detect_list_intent(user_input: str) -> bool:
    """Return True when the user prompt asks for a ranked or enumerated list."""
    return any(pattern.search(user_input) for pattern in _LIST_INTENT_PATTERNS)


def has_numbered_list(content: str) -> bool:
    """Return True when content already contains a numbered markdown list."""
    return bool(_NUMBERED_LINE_PATTERN.search(content))


def extract_list_items(content: str) -> list[str]:
    """Extract list items from bullet lines or short non-empty paragraphs."""
    bullets = [match.group(1).strip() for match in _BULLET_LINE_PATTERN.finditer(content)]
    if bullets:
        return [item for item in bullets if item]

    paragraphs: list[str] = []
    for block in content.split("\n\n"):
        stripped = block.strip()
        if not stripped or stripped.startswith("#"):
            continue
        line = stripped.replace("\n", " ").strip()
        if line and not _NUMBERED_LINE_PATTERN.match(line):
            paragraphs.append(line)

    return paragraphs


def extract_list_title(user_input: str) -> str:
    """Derive a short title for a ranked list from the user prompt."""
    cleaned = user_input.strip().rstrip("?.!")
    if len(cleaned) <= 80:
        return cleaned
    return cleaned[:77].rstrip() + "…"


def format_as_ranked_list(items: list[str], title: str) -> str:
    """Format items as a numbered markdown list with a heading."""
    lines = [f"## {title}", ""]
    for index, item in enumerate(items, 1):
        lines.append(f"{index}. {item}")
    return "\n".join(lines)


def apply_list_format(content: str, user_input: str) -> tuple[str, str | None]:
    """Reformat content as a ranked list when intent matches and items are extractable."""
    if not detect_list_intent(user_input):
        return content, None

    if has_numbered_list(content):
        return content, "ranked_list"

    items = extract_list_items(content)
    if len(items) < 2:
        return content, None

    title = extract_list_title(user_input)
    return format_as_ranked_list(items, title), "ranked_list"
