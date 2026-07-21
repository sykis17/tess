"""Per-operator ops admin token resolution (env-based)."""

from __future__ import annotations

import json
import secrets
from typing import Annotated

from fastapi import Header, HTTPException

from app.core.config import settings

LEGACY_OPERATOR_ID = "legacy"


def load_admin_tokens() -> dict[str, str]:
    """
    Return operator_id -> plaintext token.

    Primary: OPS_ADMIN_TOKENS JSON object {"jesse":"secret",...}.
    Legacy: OPS_ADMIN_TOKEN maps to operator id "legacy" when set.
    If both define the same secret, the named OPS_ADMIN_TOKENS entry wins
    for matching order (legacy still listed last for compare sweep).
    """
    tokens: dict[str, str] = {}
    raw = (settings.ops_admin_tokens or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=503,
                detail="OPS_ADMIN_TOKENS must be a JSON object of operator_id -> token",
            ) from exc
        if not isinstance(parsed, dict) or not parsed:
            raise HTTPException(
                status_code=503,
                detail="OPS_ADMIN_TOKENS must be a non-empty JSON object",
            )
        for key, value in parsed.items():
            op_id = str(key).strip()
            secret = str(value).strip() if value is not None else ""
            if not op_id or not secret:
                raise HTTPException(
                    status_code=503,
                    detail="OPS_ADMIN_TOKENS entries must be non-empty strings",
                )
            tokens[op_id] = secret

    legacy = (settings.ops_admin_token or "").strip()
    if legacy and LEGACY_OPERATOR_ID not in tokens:
        tokens[LEGACY_OPERATOR_ID] = legacy

    return tokens


def resolve_operator(authorization: str | None) -> str:
    """
    Validate Bearer token and return operator_id.

    Fail closed: if no tokens configured → 503.
    Missing/malformed Bearer → 401; wrong token → 403.
    """
    tokens = load_admin_tokens()
    if not tokens:
        raise HTTPException(
            status_code=503,
            detail=(
                "OPS_ADMIN_TOKENS or OPS_ADMIN_TOKEN must be configured before "
                "accessing gated ops endpoints (including force switch, which "
                "drops in-flight sessions)."
            ),
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    provided = authorization.removeprefix("Bearer ").strip()
    if not provided:
        raise HTTPException(status_code=401, detail="Bearer token required")

    matched_id: str | None = None
    # Always sweep all candidates (constant-time per equal-length pair).
    for op_id, secret in tokens.items():
        if len(provided) == len(secret) and secrets.compare_digest(provided, secret):
            matched_id = op_id

    if matched_id is None:
        raise HTTPException(status_code=403, detail="Invalid admin token")
    return matched_id


def require_admin(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """FastAPI dependency: return authenticated operator_id."""
    return resolve_operator(authorization)


def _check_admin(authorization: str | None) -> None:
    """Backward-compatible gate used by older tests; prefer require_admin."""
    resolve_operator(authorization)
