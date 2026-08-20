"""Synchronous LangGraph assembly for the PaperPilot research workflow."""

from collections.abc import Callable
from typing import cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from .routing import (
    END_NODE,
    HUMAN_REVIEW_NODE,
    INGESTION_NODE,
    PLANNER_NODE,
    QUALITY_GATE_NODE,
    READER_NODE,
    RETRIEVER_NODE,
    VERIFIER_NODE,
    route_after_ingestion,
    route_after_planner,
    route_after_quality_gate,
    route_after_reading,
    route_after_retrieval,
    route_after_verification,
)
from .state import ResearchState

ResearchNode = Callable[[ResearchState], ResearchState]


def human_review_node(state: ResearchState) -> ResearchState:
    """Mark a run for external review without changing its workflow decision."""

    updated = dict(state)
    updated["terminal_reason"] = "human_review_required"
    return cast(ResearchState, updated)


def build_research_graph(
    planner_node: ResearchNode,
    retriever_node: ResearchNode,
    ingestion_node: ResearchNode,
    reader_node: ResearchNode,
    verifier_node: ResearchNode,
    quality_gate_node: ResearchNode,
) -> StateGraph:
    """Build an uncompiled graph from dependency-injected synchronous nodes."""

    graph = StateGraph(ResearchState)
    graph.add_node(PLANNER_NODE, planner_node)
    graph.add_node(RETRIEVER_NODE, retriever_node)
    graph.add_node(INGESTION_NODE, ingestion_node)
    graph.add_node(READER_NODE, reader_node)
    graph.add_node(VERIFIER_NODE, verifier_node)
    graph.add_node(QUALITY_GATE_NODE, quality_gate_node)
    graph.add_node(HUMAN_REVIEW_NODE, human_review_node)

    graph.add_edge(START, PLANNER_NODE)
    graph.add_conditional_edges(
        PLANNER_NODE,
        route_after_planner,
        {
            RETRIEVER_NODE: RETRIEVER_NODE,
            QUALITY_GATE_NODE: QUALITY_GATE_NODE,
            END_NODE: END,
        },
    )
    graph.add_conditional_edges(
        RETRIEVER_NODE,
        route_after_retrieval,
        {
            RETRIEVER_NODE: RETRIEVER_NODE,
            INGESTION_NODE: INGESTION_NODE,
            QUALITY_GATE_NODE: QUALITY_GATE_NODE,
        },
    )
    graph.add_conditional_edges(
        INGESTION_NODE,
        route_after_ingestion,
        {
            INGESTION_NODE: INGESTION_NODE,
            READER_NODE: READER_NODE,
            QUALITY_GATE_NODE: QUALITY_GATE_NODE,
        },
    )
    graph.add_conditional_edges(
        READER_NODE,
        route_after_reading,
        {
            READER_NODE: READER_NODE,
            VERIFIER_NODE: VERIFIER_NODE,
            QUALITY_GATE_NODE: QUALITY_GATE_NODE,
        },
    )
    graph.add_conditional_edges(
        VERIFIER_NODE,
        route_after_verification,
        {
            VERIFIER_NODE: VERIFIER_NODE,
            QUALITY_GATE_NODE: QUALITY_GATE_NODE,
        },
    )
    graph.add_conditional_edges(
        QUALITY_GATE_NODE,
        route_after_quality_gate,
        {
            RETRIEVER_NODE: RETRIEVER_NODE,
            INGESTION_NODE: INGESTION_NODE,
            READER_NODE: READER_NODE,
            VERIFIER_NODE: VERIFIER_NODE,
            HUMAN_REVIEW_NODE: HUMAN_REVIEW_NODE,
            END_NODE: END,
        },
    )
    graph.add_edge(HUMAN_REVIEW_NODE, END)
    return graph


def compile_research_graph(
    planner_node: ResearchNode,
    retriever_node: ResearchNode,
    ingestion_node: ResearchNode,
    reader_node: ResearchNode,
    verifier_node: ResearchNode,
    quality_gate_node: ResearchNode,
) -> CompiledStateGraph:
    """Build and compile a synchronous graph without persistence or memory."""

    graph = build_research_graph(
        planner_node,
        retriever_node,
        ingestion_node,
        reader_node,
        verifier_node,
        quality_gate_node,
    )
    return graph.compile(checkpointer=None)
