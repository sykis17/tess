"""Regression guards for the L3 unbounded defense loop (W2 S2 eval-harness find).

The eval harness's first live smoke run caught this: on search-allowed profiles
that gate out combiners (L3), a revise verdict routed to combiner_micro — a
node whose micro_data input can never exist there — and the no-micro_data
early return never incremented defense_retry_count, so the retry cap never
engaged. The loop ran unbounded (killed at ~575s in-process; production hides
it behind Celery's 720s hard kill).
"""

import asyncio

from app.graph.nodes.combiner_micro import combiner_micro_node
from app.graph.routing import route_after_defense
from app.graph.schemas import DefenseChecks, DefenseReview, UsableAnswer


def _revise_review(segment_id: str = "s1") -> DefenseReview:
    return DefenseReview(
        segment_id=segment_id,
        checks=DefenseChecks(big_picture="pass", detail="pass", implication="revise"),
        verdict="revise",
    )


def _l3_loop_state() -> dict:
    # The exact inconsistent state the harness observed live: L3 gates combiners
    # out by profile, yet combiners_bypassed=False (2 agents + search results).
    return {
        "chain_profile": "L3",
        "combiners_bypassed": False,
        "active_agents": ["biology", "researcher"],
        "defense_reviews": [_revise_review()],
        "defense_retry_count": 0,
        "usable_answers": [
            UsableAnswer(segment_id="s1", order_hint=1, title="t", content="c")
        ],
    }


def test_l3_revise_routes_to_specialist_not_combiner_micro():
    # Pre-fix this returned "combiner_micro" — the entry to the unbounded loop.
    assert route_after_defense(_l3_loop_state()) == "biology"


def test_l4_revise_still_routes_to_combiner_micro():
    state = {**_l3_loop_state(), "chain_profile": "L4"}
    assert route_after_defense(state) == "combiner_micro"


def test_retry_cap_still_ends_the_loop():
    state = {**_l3_loop_state(), "defense_retry_count": 1}
    assert route_after_defense(state) == "presenter"


def test_combiner_micro_early_return_counts_the_retry():
    state = {
        "micro_data": None,
        "active_agents": ["biology"],
        "defense_notes": "address segment s1",
        "defense_retry_count": 0,
        "user_input": "x",
    }
    result = asyncio.run(combiner_micro_node(state))
    assert result["usable_answers"] == []
    # Pre-fix the early return dropped the increment — the cap could never engage.
    assert result["defense_retry_count"] == 1


def test_combiner_micro_early_return_without_notes_does_not_count():
    state = {"micro_data": None, "active_agents": ["biology"], "user_input": "x"}
    result = asyncio.run(combiner_micro_node(state))
    assert "defense_retry_count" not in result
