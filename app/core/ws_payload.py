"""WebSocket payload parsing — plain text or JSON envelope with product_mode."""

import json

from app.core.product_modes import validate_product_mode


def parse_incoming_payload(raw: str) -> tuple[str, str]:
    """Return (user_text, product_mode). Plain text → (raw, 'auto')."""
    stripped = raw.strip()
    if not stripped:
        return raw, "auto"

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return raw, "auto"

    if not isinstance(data, dict):
        return raw, "auto"

    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        return raw, "auto"

    product_mode = validate_product_mode(data.get("product_mode"))
    return text.strip(), product_mode
