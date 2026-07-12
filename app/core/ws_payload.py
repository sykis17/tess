"""WebSocket payload parsing — plain text or JSON envelope with product_mode and chain_profile."""

import json

from app.core.chain_profiles import resolve_chain_profile
from app.core.product_modes import validate_product_mode


def parse_incoming_payload(raw: str) -> tuple[str, str, str]:
    """Return (user_text, product_mode, chain_profile). Plain text → (raw, 'auto', 'L4')."""
    stripped = raw.strip()
    if not stripped:
        return raw, "auto", "L4"

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return raw, "auto", "L4"

    if not isinstance(data, dict):
        return raw, "auto", "L4"

    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        return raw, "auto", "L4"

    product_mode = validate_product_mode(data.get("product_mode"))
    raw_profile = data.get("chain_profile")
    if raw_profile is not None and not isinstance(raw_profile, str):
        raw_profile = None
    chain_profile = resolve_chain_profile(
        raw_profile,
        product_mode,
        is_plain_text=False,
    )
    return text.strip(), product_mode, chain_profile
