"""Pure gate functions for chain profile depth — unit-testable skip logic."""

from app.core.chain_profiles import ChainProfile

_DEFER = "defer"


def allows_wide_receiver(profile: str) -> bool:
    """L0 skips WR; L1–L4 use Wide Receiver."""
    return profile != ChainProfile.L0.value


def allows_search(profile: str) -> bool:
    """Search pipeline runs at L3 and L4 only."""
    return profile in {ChainProfile.L3.value, ChainProfile.L4.value}


def allows_combiners(profile: str) -> bool:
    """Combiners run at L4 only (when multi-agent)."""
    return profile == ChainProfile.L4.value


def allows_defense(profile: str) -> bool:
    """Defense runs at L2, L3, and L4."""
    return profile in {
        ChainProfile.L2.value,
        ChainProfile.L3.value,
        ChainProfile.L4.value,
    }


def max_routed_agents(profile: str) -> int:
    """Cap parallel specialists after WR parse."""
    if profile in {ChainProfile.L1.value, ChainProfile.L2.value}:
        return 1
    return 3


def route_after_fan_in_target(profile: str) -> str:
    """Post-fan-in routing target; L4 returns 'defer' for existing combiner logic."""
    if profile in {ChainProfile.L1.value, ChainProfile.L1_PLUS.value}:
        return "presenter"
    if profile in {ChainProfile.L2.value, ChainProfile.L3.value}:
        return "defense_delegator"
    return _DEFER


def max_defense_retries(profile: str) -> int:
    """L4 keeps full retry budget; L2/L3 cap at one retry."""
    if profile == ChainProfile.L4.value:
        from app.graph.defense_utils import MAX_DEFENSE_RETRIES

        return MAX_DEFENSE_RETRIES
    return 1
