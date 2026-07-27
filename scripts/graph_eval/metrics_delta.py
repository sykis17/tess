"""In-process sampler for the tess_graph_ metrics (the harness's cost feed).

Reads per-prompt deltas straight from the prometheus default registry — no
servers, no exporters. Prompts run strictly sequentially, so a before/after
snapshot cleanly attributes a delta to one prompt. Snapshots must be taken
BEFORE the judge leg runs: judge calls traverse the same llm_call recorder
(as node="unknown") and would contaminate the graph-side numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import app.graph.observability as obs

_SampleKey = tuple[str, tuple[tuple[str, str], ...]]
Snapshot = dict[str, dict[_SampleKey, float]]


def _collect(metric) -> dict[_SampleKey, float]:
    out: dict[_SampleKey, float] = {}
    for family in metric.collect():
        for sample in family.samples:
            key = (sample.name, tuple(sorted(sample.labels.items())))
            out[key] = out.get(key, 0.0) + sample.value
    return out


def take_snapshot() -> Snapshot:
    return {
        "llm_tokens": _collect(obs.LLM_TOKENS),
        "llm_calls": _collect(obs.LLM_CALLS),
        "llm_cost": _collect(obs.LLM_COST),
        "node_duration": _collect(obs.NODE_DURATION),
    }


@dataclass(frozen=True)
class GraphDelta:
    """Graph-side cost of one prompt run, as registry deltas."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    llm_calls: int = 0
    node_duration_s: dict[str, float] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def _delta_sum(
    before: Snapshot,
    after: Snapshot,
    metric_key: str,
    suffix: str,
    label_filter: dict[str, str],
) -> float:
    total = 0.0
    prior = before.get(metric_key, {})
    for key, value in after.get(metric_key, {}).items():
        name, labels = key
        if not name.endswith(suffix):
            continue
        labels_dict = dict(labels)
        if all(labels_dict.get(k) == v for k, v in label_filter.items()):
            total += value - prior.get(key, 0.0)
    return total


def compute_delta(before: Snapshot, after: Snapshot) -> GraphDelta:
    node_durations: dict[str, float] = {}
    prior = before.get("node_duration", {})
    for key, value in after.get("node_duration", {}).items():
        name, labels = key
        if not name.endswith("_sum"):
            continue
        moved = value - prior.get(key, 0.0)
        if moved > 0:
            node = dict(labels).get("node", "unknown")
            node_durations[node] = node_durations.get(node, 0.0) + moved
    return GraphDelta(
        prompt_tokens=int(
            _delta_sum(before, after, "llm_tokens", "_total", {"kind": "prompt"})
        ),
        completion_tokens=int(
            _delta_sum(before, after, "llm_tokens", "_total", {"kind": "completion"})
        ),
        cost_usd=_delta_sum(before, after, "llm_cost", "_total", {}),
        llm_calls=int(_delta_sum(before, after, "llm_calls", "_total", {})),
        node_duration_s=node_durations,
    )
