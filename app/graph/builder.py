from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.nodes.general_assistant import general_assistant_node
from app.graph.nodes.presenter import presenter_node
from app.graph.nodes.wide_receiver import wide_receiver_node
from app.graph.routing import route_after_wr
from app.graph.state import GraphState


def build_graph() -> CompiledStateGraph:
    """Construct and compile the core TESS LangGraph orchestration chain."""
    builder = StateGraph(GraphState)

    builder.add_node("wide_receiver", wide_receiver_node)
    builder.add_node("general_assistant", general_assistant_node)
    builder.add_node("presenter", presenter_node)

    builder.add_edge(START, "wide_receiver")
    builder.add_conditional_edges(
        "wide_receiver",
        route_after_wr,
        {"general_assistant": "general_assistant"},
    )
    builder.add_edge("general_assistant", "presenter")
    builder.add_edge("presenter", END)

    return builder.compile()


compiled_graph = build_graph()
