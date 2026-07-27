"""Structural rubric engine: strict, binary, artifact-based checks.

Rubrics inspect the merged final graph state — never live search content
(network flake is not a chain regression; ceilings absorb search latency).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scripts.graph_eval.runner import extract_answer

# The loader and the engine both reject unknown keys so a typo'd ceiling can't
# silently become a no-op check.
KNOWN_RUBRIC_KEYS = frozenset(
    {
        "expect_agents_all",
        "expect_agents_any",
        "min_mayor_data",
        "min_usable_answers",
        "expect_content_type",
        "expect_content_format",
        "min_content_chars",
        "max_wall_s",
        "max_total_tokens",
    }
)


@dataclass(frozen=True)
class StructuralResult:
    passed: bool
    failures: tuple[str, ...]


def evaluate_structural(
    final_state: dict[str, Any],
    rubric: dict[str, Any],
    *,
    wall_s: float,
    total_tokens: int,
) -> StructuralResult:
    unknown = set(rubric) - KNOWN_RUBRIC_KEYS
    if unknown:
        raise ValueError(f"unknown rubric keys: {sorted(unknown)}")

    failures: list[str] = []

    panels = final_state.get("panels") or []
    completed = [p for p in panels if getattr(p, "status", None) == "completed"]
    if not completed:
        failures.append("no completed panel")
    final_panel = completed[-1] if completed else None

    ran_agents = sorted({m.source_agent for m in final_state.get("mayor_data") or []})
    for agent in rubric.get("expect_agents_all", []):
        if agent not in ran_agents:
            failures.append(f"expected agent missing: {agent} (ran: {ran_agents or 'none'})")
    agents_any = rubric.get("expect_agents_any", [])
    if agents_any and not (set(agents_any) & set(ran_agents)):
        failures.append(f"none of expected agents ran: {agents_any} (ran: {ran_agents or 'none'})")

    min_mayor = rubric.get("min_mayor_data")
    mayor_count = len(final_state.get("mayor_data") or [])
    if min_mayor is not None and mayor_count < min_mayor:
        failures.append(f"mayor_data count {mayor_count} < min {min_mayor}")

    min_usable = rubric.get("min_usable_answers")
    usable_count = len(final_state.get("usable_answers") or [])
    if min_usable is not None and usable_count < min_usable:
        failures.append(f"usable_answers count {usable_count} < min {min_usable}")

    content = extract_answer(final_state)
    min_chars = rubric.get("min_content_chars", 1)
    if len(content) < min_chars:
        failures.append(f"content length {len(content)} < min {min_chars}")

    if final_panel is not None:
        expect_type = rubric.get("expect_content_type")
        if expect_type is not None and final_panel.content_type != expect_type:
            failures.append(
                f"content_type {final_panel.content_type!r} != expected {expect_type!r}"
            )
        expect_format = rubric.get("expect_content_format")
        if expect_format is not None and final_panel.content_format != expect_format:
            failures.append(
                f"content_format {final_panel.content_format!r} != expected {expect_format!r}"
            )

    max_wall = rubric.get("max_wall_s")
    if max_wall is not None and wall_s > max_wall:
        failures.append(f"wall {wall_s:.1f}s > ceiling {max_wall}s")

    max_tokens = rubric.get("max_total_tokens")
    if max_tokens is not None and total_tokens > max_tokens:
        failures.append(f"total tokens {total_tokens} > ceiling {max_tokens}")

    return StructuralResult(passed=not failures, failures=tuple(failures))
