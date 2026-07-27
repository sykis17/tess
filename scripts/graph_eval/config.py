"""Eval harness configuration.

Identity is part of the measurement: the resolved graph provider/model and the
judge provider/model/prompt-version are asserted at startup and recorded in
every history row — a score without identity is not a baseline.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.core.config import settings

# Judge score (0-10) at or above which a prompt's judge leg passes.
# Re-baseline: 6 set from the first green smoke run (S2 commit 3, llama3.2 judge,
# judge prompt v1); a change is a deliberate re-baseline event, never a mid-arc bump.
JUDGE_PASS_THRESHOLD = 6


@dataclass(frozen=True)
class EvalConfig:
    judge_provider: str
    judge_model: str
    judge_temperature: float
    judge_pass_threshold: int
    db_path: str


def default_db_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.db")


def load_config() -> EvalConfig:
    return EvalConfig(
        judge_provider=os.environ.get("GRAPH_EVAL_JUDGE_PROVIDER", "ollama"),
        judge_model=os.environ.get("GRAPH_EVAL_JUDGE_MODEL", settings.ollama_model),
        # The judge is pinned at 0.0; the graph side is deliberately NOT pinned
        # (product default temperature) — see docs/W2_S2_OPENER.md question (b).
        judge_temperature=0.0,
        judge_pass_threshold=JUDGE_PASS_THRESHOLD,
        db_path=os.environ.get("GRAPH_EVAL_HISTORY_DB", default_db_path()),
    )


def resolve_graph_identity() -> tuple[str, str]:
    """Resolved graph-side provider/model, recorded per run."""
    provider = settings.default_llm_provider
    model = settings.ollama_model if provider == "ollama" else settings.gemini_model
    return provider, model
