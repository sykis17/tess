"""In-process egress canary (P2 Step 4).

The canary proves the posture guard refuses third-party egress from INSIDE the
process: it invokes the guard primitive against a pinned inert target and, if
the guard does not stop it, actually attempts the dial — so a present guard is
proven to intercept BEFORE any socket opens, and an absent guard is loudly
visible instead of vacuously green.

Counting rule (anti-vacuity): only ``EgressRefusedError`` — checked by exact
``isinstance`` on that subclass, never bare ``ValueError`` — counts as
"refused by our own guard". A network failure (DNS, connect, egress-blocked
compose network) is classified ``guard-missing``: an environment that happens
to block egress must never impersonate the in-process guard.

Canary target: ``https://egress-canary.invalid/`` — RFC 2606 reserved TLD,
never resolvable, so no real host is ever contacted even on regression (no
phone-home shape); a regression dial fails DNS, which is NOT a refusal, so
sovereign-strict fails loudly.
"""

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.core.posture import EgressRefusedError, RuntimePosture

logger = logging.getLogger(__name__)

CANARY_TARGET_URL = "https://egress-canary.invalid/"

OUTCOME_REFUSED = "refused-by-guard"
OUTCOME_NOT_APPLICABLE = "not-applicable"
OUTCOME_GUARD_MISSING = "guard-missing"


@dataclass(frozen=True)
class CanaryResult:
    posture: str
    outcome: str
    detail: str
    checked_at: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


_last_result: CanaryResult | None = None


def get_cached_result() -> CanaryResult | None:
    """Most recent canary result in this process (startup or on-demand)."""
    return _last_result


def ensure_egress_allowed(operation: str, target: str) -> None:
    """The guard primitive every third-party egress seam calls pre-socket."""
    if settings.posture_is_strict():
        raise EgressRefusedError(
            f"sovereign-strict posture refuses third-party egress ({operation} -> {target})"
        )


def _attempt_canary_fetch() -> None:
    ensure_egress_allowed("egress-canary", CANARY_TARGET_URL)
    # Guard did not refuse: prove it by attempting the dial. The .invalid
    # target keeps even this path inert — it can only fail DNS, and that
    # failure is classified guard-missing, never refusal.
    with httpx.Client(timeout=httpx.Timeout(3.0)) as client:
        client.get(CANARY_TARGET_URL)


def run_canary() -> CanaryResult:
    """Run the canary for the current posture; never dials under availability-first."""
    global _last_result
    posture = settings.runtime_posture()
    checked_at = datetime.now(timezone.utc).isoformat()

    if posture is not RuntimePosture.SOVEREIGN_STRICT:
        result = CanaryResult(
            posture=posture.value,
            outcome=OUTCOME_NOT_APPLICABLE,
            detail="canary dials only under sovereign-strict; no egress attempted",
            checked_at=checked_at,
        )
        _last_result = result
        return result

    try:
        _attempt_canary_fetch()
    except Exception as exc:  # noqa: BLE001 — every failure shape must be classified
        if isinstance(exc, EgressRefusedError):
            result = CanaryResult(
                posture=posture.value,
                outcome=OUTCOME_REFUSED,
                detail=str(exc),
                checked_at=checked_at,
            )
        else:
            result = CanaryResult(
                posture=posture.value,
                outcome=OUTCOME_GUARD_MISSING,
                detail=(
                    f"canary attempt failed outside the guard "
                    f"({type(exc).__name__}: {exc}) — network failure is not refusal"
                ),
                checked_at=checked_at,
            )
    else:
        result = CanaryResult(
            posture=posture.value,
            outcome=OUTCOME_GUARD_MISSING,
            detail="canary fetch completed; egress was NOT refused by the guard",
            checked_at=checked_at,
        )

    _last_result = result
    return result


def verify_posture_or_raise() -> CanaryResult:
    """Startup hook (web lifespan + worker init): strict must prove refusal.

    Under sovereign-strict an unproven guard raises so the process refuses to
    start (fail-closed, loud). Under availability-first this records
    not-applicable and returns.
    """
    result = run_canary()
    if settings.posture_is_strict() and result.outcome != OUTCOME_REFUSED:
        raise RuntimeError(
            f"sovereign-strict posture UNPROVEN at startup: {result.detail}"
        )
    logger.info("Egress canary: posture=%s outcome=%s", result.posture, result.outcome)
    return result
