"""Chain profile registry — output depth levels L0–L4 that gate graph stages."""

from enum import Enum

from app.core.product_modes import ProductMode


class ChainProfile(str, Enum):
    """User-selectable output depth levels."""

    L0 = "L0"
    L1 = "L1"
    L1_PLUS = "L1+"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


PROFILE_LABELS: dict[str, str] = {
    ChainProfile.L0.value: "Direct",
    ChainProfile.L1.value: "Routed",
    ChainProfile.L1_PLUS.value: "Parallel",
    ChainProfile.L2.value: "Reviewed",
    ChainProfile.L3.value: "Grounded",
    ChainProfile.L4.value: "Full chain",
}

_VALID_PROFILES = frozenset({profile.value for profile in ChainProfile})

_DEFAULT_PROFILE = ChainProfile.L4.value

_MODE_DEFAULTS: dict[str, str] = {
    ProductMode.AUTO.value: ChainProfile.L4.value,
    ProductMode.RESEARCH.value: ChainProfile.L3.value,
    ProductMode.PLANNER.value: ChainProfile.L2.value,
    ProductMode.CODING.value: ChainProfile.L1.value,
    ProductMode.BUILDER.value: ChainProfile.L4.value,
}


def validate_chain_profile(profile: str | None) -> str:
    """Return a valid profile key; unknown or missing values map to L4."""
    if profile and profile in _VALID_PROFILES:
        return profile
    return _DEFAULT_PROFILE


def default_for_product_mode(product_mode: str) -> str:
    """Default chain profile when the client omits chain_profile in JSON."""
    return _MODE_DEFAULTS.get(product_mode, _DEFAULT_PROFILE)


def resolve_chain_profile(
    raw_profile: str | None,
    product_mode: str,
    *,
    is_plain_text: bool,
) -> str:
    """Resolve the effective chain profile from payload and product mode."""
    if is_plain_text:
        return _DEFAULT_PROFILE
    if raw_profile is not None:
        return validate_chain_profile(raw_profile)
    return default_for_product_mode(product_mode)
