"""Storage-independent checkpoint contract."""

from typing import Protocol, runtime_checkable
from uuid import UUID

from paperpilot.orchestration.state import ResearchState

from .models import CheckpointRecord


@runtime_checkable
class CheckpointStore(Protocol):
    """Persist and retrieve isolated research state snapshots by run ID."""

    def save(self, run_id: UUID, state: ResearchState) -> CheckpointRecord:
        """Save a state snapshot, replacing any snapshot for the same run."""

        ...

    def load(self, run_id: UUID) -> CheckpointRecord:
        """Load an isolated copy of a run's checkpoint record."""

        ...

    def delete(self, run_id: UUID) -> bool:
        """Delete a run's checkpoint and report whether it existed."""

        ...

    def exists(self, run_id: UUID) -> bool:
        """Return whether a checkpoint exists for a run."""

        ...
