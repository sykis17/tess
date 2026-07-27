"""Token→price map for graph cost metrics (W2).

A module dict, not a config file, on purpose: prices should change under code review,
and a config file adds parse/IO failure modes to a path that must never raise.

Unknown models cost 0.0 — which deliberately covers every Ollama/local model. Match is
exact first, then longest-prefix (handles dated/`-001`-style suffixes).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelCost:
    prompt_usd_per_1m: float
    completion_usd_per_1m: float


# Gemini API list prices, USD per 1M tokens (standard tier, prompt <= 200k), as published
# 2026-07. Edit here when prices or configured models change.
MODEL_COSTS: dict[str, ModelCost] = {
    "gemini-2.0-flash-lite": ModelCost(0.075, 0.30),
    "gemini-2.0-flash": ModelCost(0.10, 0.40),
    "gemini-2.5-flash": ModelCost(0.30, 2.50),
    "gemini-2.5-pro": ModelCost(1.25, 10.00),
}


def cost_usd(
    model: str | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> float:
    """Estimated USD cost of one call; 0.0 for unknown models or unusable token counts."""
    if not model or not isinstance(model, str):
        return 0.0
    cost = MODEL_COSTS.get(model)
    if cost is None:
        prefixes = [key for key in MODEL_COSTS if model.startswith(key)]
        if not prefixes:
            return 0.0
        cost = MODEL_COSTS[max(prefixes, key=len)]
    pt = prompt_tokens if isinstance(prompt_tokens, int) and prompt_tokens > 0 else 0
    ct = completion_tokens if isinstance(completion_tokens, int) and completion_tokens > 0 else 0
    return (pt * cost.prompt_usd_per_1m + ct * cost.completion_usd_per_1m) / 1_000_000
