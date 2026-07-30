"""Runtime posture: the deployment's egress stance (P2 Step 4).

Posture is a deployment stance, not routing behavior — it is deliberately
distinct from ``product_modes`` / ``chain_profiles`` and must never reuse
their keys (product_mode is a bounded metric label; posture is never a label).

Unlike ``validate_product_mode`` / ``validate_chain_profile``, which fold
unknown values to a default, an unknown posture RAISES: a typo'd posture must
fail the process closed at startup, never run permissive.
"""

from enum import Enum
from ipaddress import ip_address
from urllib.parse import urlsplit


class RuntimePosture(str, Enum):
    """``sovereign-strict`` refuses third-party egress in-process at the
    LLM-factory and search seams; ``availability-first`` is the historical
    behavior, unchanged."""

    SOVEREIGN_STRICT = "sovereign-strict"
    AVAILABILITY_FIRST = "availability-first"


class EgressRefusedError(ValueError):
    """Raised by posture guards when sovereign-strict refuses third-party egress.

    Subclasses ValueError so the LLM factory's refusal matches the existing
    config-driven refusal shape (GeminiLLM's missing-key ValueError). Anything
    that COUNTS refusals (the egress canary) must check this type specifically
    — a bare ``except ValueError`` would misattribute unrelated config errors
    as guard refusals.
    """


def resolve_posture(value: str) -> RuntimePosture:
    """Return the posture for ``value``; unknown values raise (fail-closed)."""
    try:
        return RuntimePosture(value)
    except ValueError:
        expected = ", ".join(p.value for p in RuntimePosture)
        raise ValueError(
            f"Unknown TESS_RUNTIME_POSTURE {value!r}; expected one of: {expected}"
        ) from None


# Multi-label hostnames that are docker-internal by convention, not public DNS.
_INTERNAL_HOSTNAME_ALLOWLIST = frozenset({"localhost", "host.docker.internal"})


def is_internal_base_url(url: str) -> bool:
    """True when ``url``'s host points at loopback/private infrastructure.

    Deterministic — no DNS at boot. Allows: IP literals in loopback / private
    (RFC 1918, IPv6 unique-local) / link-local ranges; single-label hostnames
    (docker service names such as ``ollama``, resolvable only via internal
    DNS); and the explicit allowlist above. Public IP literals and multi-label
    public hostnames are refused under sovereign-strict.
    """
    host = urlsplit(url).hostname
    if not host:
        return False
    try:
        addr = ip_address(host)
    except ValueError:
        if host in _INTERNAL_HOSTNAME_ALLOWLIST:
            return True
        return "." not in host
    return addr.is_loopback or addr.is_private or addr.is_link_local
