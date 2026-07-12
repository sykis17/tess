"""Utilities for synchronizing parallel fan-out branches at post_fan_in."""

from app.graph.state import GraphState

RESOURCE_READER_BRANCH = "resource_reader"


def build_expected_fan_in_branches(active_agents: list[str], search_queries: list[str]) -> list[str]:
    """Return branch IDs that must complete before post_fan_in may route downstream."""
    branches = list(active_agents)
    if search_queries:
        branches.append(RESOURCE_READER_BRANCH)
    return branches


def fan_in_branch_complete(state: GraphState, branch_id: str) -> dict[str, list[str]]:
    """Mark a parallel branch as finished for fan-in coordination."""
    return {"fan_in_branches_done": [branch_id]}


def all_fan_in_branches_complete(state: GraphState) -> bool:
    """Return True when every expected parallel branch has reported completion."""
    expected = set(state.get("expected_fan_in_branches") or [])
    done = set(state.get("fan_in_branches_done") or [])
    return bool(expected) and expected.issubset(done)
