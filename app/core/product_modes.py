"""Product mode registry — intent profiles that steer WR routing and prompts."""

from dataclasses import dataclass
from enum import Enum


class ProductMode(str, Enum):
    """User-facing intent profiles (not separate graphs)."""

    AUTO = "auto"
    RESEARCH = "research"
    PLANNER = "planner"
    CODING = "coding"
    BUILDER = "builder"


@dataclass(frozen=True)
class ProductModeConfig:
    """Per-mode display name and compact prompt/routing hints."""

    display_name: str
    wr_rules: str
    combiner_hint: str | None = None
    defense_hint: str | None = None
    # Implicit chain bias (Phase 17 will expose L0–L4 UI; documented here only):
    # research → L3+ (defense + search encouraged)
    # planner → L2+ (defense always)
    # coding → L1–L2 (defense; combiner bypass OK for single coder)
    # builder → L4 (multi-agent + combiners when 2+ agents)


MODES: dict[str, ProductModeConfig] = {
    ProductMode.RESEARCH.value: ProductModeConfig(
        display_name="Research",
        wr_rules=(
            "Active product mode: research\n"
            "- Favor search_queries when the user needs citations, sources, or grounded facts.\n"
            "- Prefer multi-POV routing when the question spans disciplines.\n"
            "- Do not route casual chat to researcher."
        ),
        combiner_hint="Catalog per-source inventory; Micro should write synthesis with explicit source agreement.",
        defense_hint="Stricter on unsupported claims; flag missing citations when user asked for sources.",
    ),
    ProductMode.PLANNER.value: ProductModeConfig(
        display_name="Planner",
        wr_rules=(
            "Active product mode: planner\n"
            "- Structure output as a plan, timeline, or checklist in current_task.\n"
            "- Route to domain-matching agents; usually 1–2 agents unless clearly multi-POV.\n"
            "- Search only when the plan needs external facts."
        ),
        combiner_hint="Micro output should use numbered phases, milestones, and durations where inferable.",
        defense_hint="Check for actionable steps, ordering, and missing dependencies.",
    ),
    ProductMode.CODING.value: ProductModeConfig(
        display_name="Coding",
        wr_rules=(
            "Active product mode: coding\n"
            "- Primary agent: coder. Add researcher only for external API/docs lookup.\n"
            "- Avoid POV agents unless code explicitly serves a domain (e.g. chemistry simulation)."
        ),
        combiner_hint="If multi-agent, merge code + explanation without duplicating snippets.",
        defense_hint="Check code completeness, obvious syntax issues, and language/framework alignment.",
    ),
    ProductMode.BUILDER.value: ProductModeConfig(
        display_name="Builder",
        wr_rules=(
            "Active product mode: builder\n"
            "- Alarm 2–3 agents across artifact types: coder, media (photo/video/audio), relevant POV.\n"
            "- current_task should list expected deliverables.\n"
            "- Search when external references are needed."
        ),
        combiner_hint="Group by artifact type; Micro produces one section per deliverable.",
        defense_hint="Check all requested artifact types are present; flag gaps.",
    ),
}

_VALID_MODES = frozenset({mode.value for mode in ProductMode})


def validate_product_mode(mode: str | None) -> str:
    """Return a valid mode key; unknown or missing values map to auto."""
    if mode and mode in _VALID_MODES:
        return mode
    return ProductMode.AUTO.value


def get_wr_rules_block(mode: str) -> str:
    """Return WR system-prompt appendix for the given mode; empty for auto."""
    if mode == ProductMode.AUTO.value:
        return ""
    config = MODES.get(mode)
    if config is None:
        return ""
    return f"\n\n{config.wr_rules}"


def get_combiner_hint(mode: str) -> str | None:
    """Return optional combiner prompt hint for the given mode."""
    if mode == ProductMode.AUTO.value:
        return None
    config = MODES.get(mode)
    return config.combiner_hint if config else None


def get_defense_hint(mode: str) -> str | None:
    """Return optional defense prompt hint for the given mode."""
    if mode == ProductMode.AUTO.value:
        return None
    config = MODES.get(mode)
    return config.defense_hint if config else None
