"""Public dependency-injected factory for a compiled research graph."""

from langgraph.graph.state import CompiledStateGraph

from .graph import ResearchNode, compile_research_graph


def create_research_graph(
    planner_node: ResearchNode,
    retriever_node: ResearchNode,
    ingestion_node: ResearchNode,
    reader_node: ResearchNode,
    verifier_node: ResearchNode,
    quality_gate_node: ResearchNode,
) -> CompiledStateGraph:
    """Return a compiled graph using only the supplied node dependencies."""

    return compile_research_graph(
        planner_node,
        retriever_node,
        ingestion_node,
        reader_node,
        verifier_node,
        quality_gate_node,
    )
