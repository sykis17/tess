"""Provider-agnostic token-usage extraction from LangChain messages/chunks (W2).

Pure and defensive: never raises, degrades to ``(None, None)``. Feeds both the
``tess_graph_llm_tokens`` metrics (via ``app.graph.observability.llm_call``) and the
``LLMResponse.prompt_tokens / completion_tokens`` fields the W2 eval harness reads.
"""

from __future__ import annotations

from typing import Any


def extract_usage(message: Any) -> tuple[int | None, int | None]:
    """Best-effort ``(prompt_tokens, completion_tokens)`` from an AIMessage/chunk.

    Tries the standardized ``usage_metadata`` first (both pinned providers populate it
    on ``ainvoke`` results and on the final stream chunk), then falls back to Ollama's
    ``response_metadata`` counters (``prompt_eval_count`` / ``eval_count``).
    """
    try:
        usage = getattr(message, "usage_metadata", None)
        if usage:
            pt = usage.get("input_tokens")
            ct = usage.get("output_tokens")
            if pt is not None or ct is not None:
                return (
                    pt if isinstance(pt, int) else None,
                    ct if isinstance(ct, int) else None,
                )
        meta = getattr(message, "response_metadata", None) or {}
        pt = meta.get("prompt_eval_count")
        ct = meta.get("eval_count")
        return (
            pt if isinstance(pt, int) else None,
            ct if isinstance(ct, int) else None,
        )
    except Exception:
        return (None, None)
