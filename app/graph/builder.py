from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.registry import AGENT_REGISTRY
from app.graph.nodes.coder import coder_node
from app.graph.nodes.general_assistant import general_assistant_node
from app.graph.nodes.presenter import presenter_node
from app.graph.nodes.researcher import researcher_node
from app.graph.nodes.wide_receiver import wide_receiver_node
from app.graph.routing import fan_out_to_specialists
from app.graph.state import GraphState

_SPECIALIST_NODES = {
    "general_assistant": general_assistant_node,
    "coder": coder_node,
    "researcher": researcher_node,
}


def build_graph() -> CompiledStateGraph:
    """Construct and compile the core TESS LangGraph orchestration chain."""
    builder = StateGraph(GraphState)

    builder.add_node("wide_receiver", wide_receiver_node)
    builder.add_node("presenter", presenter_node)

    for name in AGENT_REGISTRY:
        builder.add_node(name, _SPECIALIST_NODES[name])
        builder.add_edge(name, "presenter")

    builder.add_edge(START, "wide_receiver")
    builder.add_conditional_edges("wide_receiver", fan_out_to_specialists)
    builder.add_edge("presenter", END)

    return builder.compile()


compiled_graph = build_graph()
