"""Unit tests for synchronous LangGraph research workflow assembly."""

import copy
import unittest

from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from paperguide.domain import PaperSource, ResearchConfig
from paperguide.orchestration import (
    NextAction,
    create_initial_state,
    create_research_graph,
)
from paperguide.orchestration.graph import (
    build_research_graph,
    compile_research_graph,
)


def make_state():
    """Create a valid empty workflow state."""

    config = ResearchConfig(
        question="Analyze SLAM",
        max_papers=5,
        sources=[PaperSource.ARXIV],
    )
    return create_initial_state(config.question, config)


class FakeNode:
    """Record inputs and return a copied state with a selected action."""

    def __init__(self, action: NextAction):
        self.action = action
        self.calls = 0
        self.inputs = []

    def __call__(self, state):
        self.calls += 1
        self.inputs.append(copy.deepcopy(state))
        updated = dict(state)
        updated["next_action"] = self.action
        return updated


def make_nodes(*, human_review: bool = False):
    """Create fake nodes that drive one complete linear execution."""

    quality_action = (
        NextAction.HUMAN_REVIEW if human_review else NextAction.COMPLETE
    )
    return (
        FakeNode(NextAction.RETRIEVE),
        FakeNode(NextAction.INGEST),
        FakeNode(NextAction.READ),
        FakeNode(NextAction.VERIFY),
        FakeNode(NextAction.EVALUATE_QUALITY),
        FakeNode(quality_action),
    )


class OrchestrationGraphTests(unittest.TestCase):
    """Verify graph construction, routing, termination, and injection."""

    def test_graph_can_be_built(self) -> None:
        graph = build_research_graph(*make_nodes())

        self.assertIsInstance(graph, StateGraph)

    def test_graph_can_be_compiled(self) -> None:
        graph = compile_research_graph(*make_nodes())

        self.assertIsInstance(graph, CompiledStateGraph)

    def test_all_nodes_are_registered(self) -> None:
        graph = build_research_graph(*make_nodes())

        self.assertEqual(
            set(graph.nodes),
            {
                "planner",
                "retriever",
                "ingestion",
                "reader",
                "verifier",
                "quality_gate",
                "human_review",
            },
        )

    def test_start_path_targets_planner(self) -> None:
        graph = build_research_graph(*make_nodes())

        self.assertIn((START, "planner"), graph.edges)

    def test_planner_routes_to_injected_retriever(self) -> None:
        nodes = make_nodes()
        graph = create_research_graph(*nodes)

        graph.invoke(make_state())

        self.assertEqual(nodes[0].calls, 1)
        self.assertEqual(nodes[1].calls, 1)

    def test_quality_complete_reaches_end(self) -> None:
        nodes = make_nodes()
        graph = create_research_graph(*nodes)

        result = graph.invoke(make_state())

        self.assertEqual(result["next_action"], NextAction.COMPLETE)
        self.assertEqual(nodes[5].calls, 1)

    def test_quality_human_review_reaches_terminal_node(self) -> None:
        nodes = make_nodes(human_review=True)
        graph = create_research_graph(*nodes)
        initial = make_state()

        result = graph.invoke(initial)

        self.assertEqual(result["next_action"], NextAction.HUMAN_REVIEW)
        self.assertEqual(result["current_step"], initial["current_step"])
        self.assertEqual(result["terminal_reason"], "human_review_required")

    def test_compiled_graph_contains_no_unknown_nodes(self) -> None:
        graph = create_research_graph(*make_nodes())

        self.assertEqual(
            set(graph.nodes),
            {
                START,
                "planner",
                "retriever",
                "ingestion",
                "reader",
                "verifier",
                "quality_gate",
                "human_review",
            },
        )

    def test_graph_execution_does_not_modify_initial_state(self) -> None:
        state = make_state()
        original = copy.deepcopy(state)
        graph = create_research_graph(*make_nodes())

        graph.invoke(state)

        self.assertEqual(state, original)

    def test_factory_uses_supplied_node_instances(self) -> None:
        nodes = make_nodes()
        graph = create_research_graph(*nodes)

        graph.invoke(make_state())

        self.assertTrue(all(node.calls == 1 for node in nodes))


if __name__ == "__main__":
    unittest.main()
