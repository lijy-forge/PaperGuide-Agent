"""A run that dies partway must not repeat the work it already finished."""

import sqlite3
import tempfile
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from paperguide.orchestration.resumable import ResumableGraph


class _Snapshot:
    def __init__(self, nxt):
        self.next = nxt


class _RecordingGraph:
    """Captures how the wrapper invoked it."""

    def __init__(self, snapshot=None, raises=False):
        self.calls = []
        self._snapshot = snapshot
        self._raises = raises

    def invoke(self, state, config=None):
        self.calls.append((state, config))
        return {"ok": True}

    def get_state(self, config):
        if self._raises:
            raise RuntimeError("no checkpoint")
        return self._snapshot


def test_a_run_with_pending_work_resumes_instead_of_restarting():
    graph = _RecordingGraph(snapshot=_Snapshot(("reader",)))

    ResumableGraph(graph).invoke({"run_id": "run-1"})

    state, config = graph.calls[0]
    # None is what continues a thread; passing a state would start it over.
    assert state is None
    assert config["configurable"]["thread_id"] == "run-1"


def test_a_finished_thread_starts_a_new_run_rather_than_returning_its_result():
    """Re-invoking a completed thread with None returns its old final state,
    which would hand back a stale report for a new request."""

    graph = _RecordingGraph(snapshot=_Snapshot(()))

    ResumableGraph(graph).invoke({"run_id": "run-1"})

    state, config = graph.calls[0]
    assert state == {"run_id": "run-1"}
    assert config["configurable"]["thread_id"] == "run-1"


def test_a_missing_checkpoint_is_a_fresh_run_not_an_error():
    graph = _RecordingGraph(raises=True)

    ResumableGraph(graph).invoke({"run_id": "run-1"})

    assert graph.calls[0][0] == {"run_id": "run-1"}


def test_a_state_with_no_identifier_runs_without_persistence():
    """Inventing a thread id would collide with another run's checkpoint."""

    graph = _RecordingGraph(snapshot=_Snapshot(("reader",)))

    ResumableGraph(graph).invoke({"question": "q"})

    state, config = graph.calls[0]
    assert state == {"question": "q"}
    assert config is None


def test_resuming_a_real_graph_does_not_rerun_completed_nodes():
    """The point of the feature: work already paid for is not paid for twice."""

    from typing import TypedDict

    from langgraph.graph import END, START, StateGraph

    class _State(TypedDict):
        done: list[str]

    failing = {"on": True}

    def first(state):
        return {"done": state["done"] + ["first"]}

    def second(state):
        if failing["on"]:
            raise RuntimeError("worker died")
        return {"done": state["done"] + ["second"]}

    with tempfile.TemporaryDirectory() as directory:
        connection = sqlite3.connect(Path(directory) / "ckpt.sqlite", check_same_thread=False)
        builder = StateGraph(_State)
        builder.add_node("first", first)
        builder.add_node("second", second)
        builder.add_edge(START, "first")
        builder.add_edge("first", "second")
        builder.add_edge("second", END)
        graph = ResumableGraph(builder.compile(checkpointer=SqliteSaver(connection)))

        try:
            graph.invoke({"run_id": "run-1", "done": []})
        except RuntimeError:
            pass

        failing["on"] = False
        result = graph.invoke({"run_id": "run-1", "done": []})

        assert result["done"] == ["first", "second"]
        assert result["done"].count("first") == 1
