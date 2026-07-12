from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.base import run_specialist
from app.agents.registry import AGENT_REGISTRY
from app.graph.nodes.combiner_mayor import combiner_mayor_node
from app.graph.nodes.combiner_micro import combiner_micro_node
from app.graph.nodes.collector import collector_node
from app.graph.nodes.defense_delegator import defense_delegator_node
from app.graph.nodes.defense_review import defense_review_node
from app.graph.nodes.fan_in_wait import fan_in_wait_node
from app.graph.nodes.post_fan_in import post_fan_in_node
from app.graph.nodes.presenter import presenter_node
from app.graph.nodes.resource_finder import resource_finder_node
from app.graph.nodes.resource_reader import resource_reader_node
from app.graph.nodes.wide_receiver import wide_receiver_node
from app.graph.routing import fan_out_from_wr, route_after_defense, route_after_fan_in
from app.graph.state import GraphState


def _make_specialist_node(agent_name: str):
    """Create a thin graph node that runs a registered specialist agent."""

    async def node(state: GraphState) -> dict[str, Any]:
        return await run_specialist(state, agent_name)

    node.__name__ = f"{agent_name}_node"
    return node


_SPECIALIST_NODES = {name: _make_specialist_node(name) for name in AGENT_REGISTRY}


def build_graph() -> CompiledStateGraph:
    """Construct and compile the core TESS LangGraph orchestration chain."""
    builder = StateGraph(GraphState)

    builder.add_node("wide_receiver", wide_receiver_node)
    builder.add_node("post_fan_in", post_fan_in_node)
    builder.add_node("fan_in_wait", fan_in_wait_node)
    builder.add_node("combiner_mayor", combiner_mayor_node)
    builder.add_node("combiner_micro", combiner_micro_node)
    builder.add_node("collector", collector_node)
    builder.add_node("defense_delegator", defense_delegator_node)
    builder.add_node("defense_review", defense_review_node)
    builder.add_node("presenter", presenter_node)
    builder.add_node("resource_finder", resource_finder_node)
    builder.add_node("resource_reader", resource_reader_node)

    for name in AGENT_REGISTRY:
        builder.add_node(name, _SPECIALIST_NODES[name])
        builder.add_edge(name, "post_fan_in")

    builder.add_edge("resource_finder", "resource_reader")
    builder.add_edge("resource_reader", "post_fan_in")

    builder.add_edge(START, "wide_receiver")
    builder.add_conditional_edges("wide_receiver", fan_out_from_wr)
    builder.add_conditional_edges("post_fan_in", route_after_fan_in)
    builder.add_edge("fan_in_wait", END)
    builder.add_edge("combiner_mayor", "combiner_micro")
    builder.add_edge("combiner_micro", "collector")
    builder.add_edge("collector", "defense_delegator")
    builder.add_edge("defense_delegator", "defense_review")
    builder.add_conditional_edges("defense_review", route_after_defense)
    builder.add_edge("presenter", END)

    return builder.compile()


compiled_graph = build_graph()
