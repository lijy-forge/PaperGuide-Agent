"""Unit tests for checkpoint contracts and isolated in-memory storage."""

import copy
import unittest
from uuid import uuid4

from pydantic import ValidationError

from paperpilot.domain import PaperSource, ResearchConfig
from paperpilot.orchestration import create_initial_state
from paperpilot.orchestration.checkpoint import (
    CheckpointNotFoundError,
    CheckpointRecord,
    CheckpointStore,
    MemoryCheckpointStore,
)


def make_state(question: str = "Analyze SLAM"):
    """Create a valid state with a unique run ID."""

    config = ResearchConfig(
        question=question,
        max_papers=5,
        sources=[PaperSource.ARXIV],
    )
    return create_initial_state(config.question, config)


class OrchestrationCheckpointTests(unittest.TestCase):
    """Verify the checkpoint protocol, lifecycle, serialization, and isolation."""

    def test_save_succeeds(self) -> None:
        store = MemoryCheckpointStore()
        state = make_state()

        record = store.save(state["run_id"], state)

        self.assertIsInstance(record, CheckpointRecord)
        self.assertEqual(record.run_id, state["run_id"])

    def test_load_succeeds(self) -> None:
        store = MemoryCheckpointStore()
        state = make_state()
        saved = store.save(state["run_id"], state)

        loaded = store.load(state["run_id"])

        self.assertEqual(loaded, saved)

    def test_missing_load_raises_not_found(self) -> None:
        store = MemoryCheckpointStore()

        with self.assertRaises(CheckpointNotFoundError):
            store.load(uuid4())

    def test_exists_tracks_saved_checkpoint(self) -> None:
        store = MemoryCheckpointStore()
        state = make_state()

        self.assertFalse(store.exists(state["run_id"]))
        store.save(state["run_id"], state)
        self.assertTrue(store.exists(state["run_id"]))

    def test_delete_reports_presence(self) -> None:
        store = MemoryCheckpointStore()
        state = make_state()
        store.save(state["run_id"], state)

        self.assertTrue(store.delete(state["run_id"]))
        self.assertFalse(store.exists(state["run_id"]))
        self.assertFalse(store.delete(state["run_id"]))

    def test_save_overwrites_old_state(self) -> None:
        store = MemoryCheckpointStore()
        state = make_state()
        first = store.save(state["run_id"], state)
        updated = copy.deepcopy(state)
        updated["warnings"].append("partial result")

        second = store.save(state["run_id"], updated)

        self.assertEqual(second.id, first.id)
        self.assertEqual(second.created_at, first.created_at)
        self.assertIn("partial result", store.load(state["run_id"]).state["warnings"])

    def test_save_does_not_modify_or_retain_input_state(self) -> None:
        store = MemoryCheckpointStore()
        state = make_state()
        original = copy.deepcopy(state)

        store.save(state["run_id"], state)
        state["warnings"].append("external mutation")

        self.assertEqual(original["warnings"], [])
        self.assertEqual(store.load(state["run_id"]).state["warnings"], [])

    def test_load_returns_an_isolated_copy(self) -> None:
        store = MemoryCheckpointStore()
        state = make_state()
        store.save(state["run_id"], state)

        loaded = store.load(state["run_id"])
        loaded.state["warnings"].append("consumer mutation")

        self.assertEqual(store.load(state["run_id"]).state["warnings"], [])

    def test_checkpoint_json_round_trip(self) -> None:
        store = MemoryCheckpointStore()
        state = make_state()
        record = store.save(state["run_id"], state)

        restored = CheckpointRecord.model_validate_json(record.model_dump_json())

        self.assertEqual(restored, record)

    def test_multiple_run_ids_are_isolated(self) -> None:
        store = MemoryCheckpointStore()
        first_state = make_state("First question")
        second_state = make_state("Second question")
        store.save(first_state["run_id"], first_state)
        store.save(second_state["run_id"], second_state)

        self.assertEqual(
            store.load(first_state["run_id"]).state["question"],
            "First question",
        )
        self.assertEqual(
            store.load(second_state["run_id"]).state["question"],
            "Second question",
        )

    def test_memory_store_satisfies_protocol(self) -> None:
        self.assertIsInstance(MemoryCheckpointStore(), CheckpointStore)

    def test_checkpoint_record_rejects_unknown_fields(self) -> None:
        state = make_state()

        with self.assertRaises(ValidationError):
            CheckpointRecord(
                run_id=state["run_id"],
                state=state,
                unexpected=True,
            )

    def test_checkpoint_record_requires_run_id(self) -> None:
        state = make_state()

        with self.assertRaises(ValidationError):
            CheckpointRecord(state=state)  # type: ignore[call-arg]


if __name__ == "__main__":
    unittest.main()
