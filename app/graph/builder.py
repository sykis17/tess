from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.base import run_specialist
from app.agents.registry import AGENT_REGISTRY
from app.graph.nodes.combiner_mayor import combiner_mayor_node
from app.graph.nodes.combiner_micro import combiner_micro_node
from app.graph.nodes.collector import collector_node
from app.graph.nodes.defense_delegator import defense_delegator_node
from app.graph.nodes.defense_review import defense_review_node
from app.graph.nodes.direct_responder import direct_responder_node
from app.graph.nodes.fan_in_wait import fan_in_wait_node
from app.graph.nodes.post_fan_in import post_fan_in_node
from app.graph.nodes.presenter import presenter_node
from app.graph.nodes.resource_finder import resource_finder_node
from app.graph.nodes.resource_reader import resource_reader_node
from app.graph.nodes.wide_receiver import wide_receiver_node
from app.graph.observability import instrument_node
from app.graph.routing import (
    fan_out_from_wr,
    route_after_defense,
    route_after_fan_in,
    route_from_start,
)
from app.graph.state import GraphState


def _make_specialist_node(agent_name: str):
    """Create a thin graph node that runs a registered specialist agent."""

    async def node(state: GraphState) -> dict[str, Any]:
        return await run_specialist(state, agent_name)

    node.__name__ = f"{agent_name}_node"
    return node


_SPECIALIST_NODES = {name: _make_specialist_node(name) for name in AGENT_REGISTRY}


def build_graph(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    """Construct and compile the core TESS LangGraph orchestration chain."""
    builder = StateGraph(GraphState)

    # Every node routes through instrument_node (a flags-off passthrough) — enforced
    # statically by tests/test_graph_metrics.py, which reads this file's source.
    builder.add_node("wide_receiver", instrument_node("wide_receiver", wide_receiver_node))
    builder.add_node("direct_responder", instrument_node("direct_responder", direct_responder_node))
    builder.add_node("post_fan_in", instrument_node("post_fan_in", post_fan_in_node))
    builder.add_node("fan_in_wait", instrument_node("fan_in_wait", fan_in_wait_node))
    builder.add_node("combiner_mayor", instrument_node("combiner_mayor", combiner_mayor_node))
    builder.add_node("combiner_micro", instrument_node("combiner_micro", combiner_micro_node))
    builder.add_node("collector", instrument_node("collector", collector_node))
    builder.add_node("defense_delegator", instrument_node("defense_delegator", defense_delegator_node))
    builder.add_node("defense_review", instrument_node("defense_review", defense_review_node))
    builder.add_node("presenter", instrument_node("presenter", presenter_node))
    builder.add_node("resource_finder", instrument_node("resource_finder", resource_finder_node))
    builder.add_node("resource_reader", instrument_node("resource_reader", resource_reader_node))

    for name in AGENT_REGISTRY:
        builder.add_node(name, instrument_node(name, _SPECIALIST_NODES[name], agent=name))
        builder.add_edge(name, "post_fan_in")

    builder.add_edge("resource_finder", "resource_reader")
    builder.add_edge("resource_reader", "post_fan_in")

    builder.add_conditional_edges(START, route_from_start)
    builder.add_edge("direct_responder", "presenter")
    builder.add_conditional_edges("wide_receiver", fan_out_from_wr)
    builder.add_conditional_edges("post_fan_in", route_after_fan_in)
    builder.add_edge("fan_in_wait", END)
    builder.add_edge("combiner_mayor", "combiner_micro")
    builder.add_edge("combiner_micro", "collector")
    builder.add_edge("collector", "defense_delegator")
    builder.add_edge("defense_delegator", "defense_review")
    builder.add_conditional_edges("defense_review", route_after_defense)
    builder.add_edge("presenter", END)

    return builder.compile(checkpointer=checkpointer)


compiled_graph = build_graph()

# W3: the bare singleton above stays eager and checkpointer-free forever — the
# zero-infra eval harness imports it and tests patch it. The checkpointed twin
# is constructed lazily at first use, never at import: an import-time saver
# would drag Redis configuration into every process that imports app.graph.
_checkpointed_graph: CompiledStateGraph | None = None
_checkpoint_saver = None


def get_checkpoint_saver():
    """The saver behind get_checkpointed_graph(), or None before first use."""
    return _checkpoint_saver


def get_checkpointed_graph() -> CompiledStateGraph:
    global _checkpointed_graph, _checkpoint_saver
    if _checkpointed_graph is None:
        from app.graph.checkpoint import RedisCheckpointSaver

        _checkpoint_saver = RedisCheckpointSaver.from_settings()
        _checkpointed_graph = build_graph(checkpointer=_checkpoint_saver)
    return _checkpointed_graph
