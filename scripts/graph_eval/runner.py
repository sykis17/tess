"""In-process graph runner: drives compiled_graph directly, zero transport infra.

With session_id="" every transport side-effect is inert — publish_panel
early-returns, specialists take the plain generate path, the interrupt poll
never touches Redis — so the measurement is the graph itself, not worker/WS
overhead.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from app.graph import compiled_graph
from app.graph.state import build_initial_state

# app.worker's module level only constructs the Celery app object (broker
# connections are lazy) and registers tasks/signal handlers, so importing the
# real helpers is side-effect-free here — single source of truth over a mirror.
from app.worker import _extract_assistant_content, _merge_node_output

from scripts.graph_eval.metrics_delta import GraphDelta, compute_delta, take_snapshot


@dataclass
class PromptRunResult:
    outcome: str  # "success" | "error"
    error: str
    wall_s: float
    final_state: dict[str, Any]
    delta: GraphDelta


async def run_prompt(
    prompt_text: str,
    *,
    chain_profile: str,
    product_mode: str,
    progress: Callable[[str], None] | None = None,
) -> PromptRunResult:
    state = build_initial_state(
        prompt_text,
        session_id="",
        product_mode=product_mode,
        chain_profile=chain_profile,
    )
    merged: dict[str, Any] = dict(state)
    before = take_snapshot()
    outcome, error = "success", ""
    started = time.monotonic()
    try:
        async for update in compiled_graph.astream(state, stream_mode="updates"):
            for node_name, node_output in update.items():
                if isinstance(node_output, dict):
                    _merge_node_output(merged, node_output)
                if progress is not None:
                    progress(node_name)
    except Exception as exc:  # noqa: BLE001 — a red prompt must not kill the run loop
        outcome, error = "error", f"{type(exc).__name__}: {exc}"
    wall_s = time.monotonic() - started
    delta = compute_delta(before, take_snapshot())
    return PromptRunResult(
        outcome=outcome,
        error=error,
        wall_s=wall_s,
        final_state=merged,
        delta=delta,
    )


def extract_answer(final_state: dict[str, Any]) -> str:
    """Final assistant content, or "" when the run produced none."""
    try:
        return _extract_assistant_content(final_state)
    except ValueError:
        return ""
