"""Process-local in-memory checkpoint store."""

from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

from paperguide.orchestration.state import ResearchState

from .exceptions import CheckpointNotFoundError
from .models import CheckpointRecord


class MemoryCheckpointStore:
    """Store deep-copied checkpoints in memory, isolated by research run ID."""

    def __init__(self) -> None:
        self._records: dict[str, CheckpointRecord] = {}

    def save(self, run_id: UUID, state: ResearchState) -> CheckpointRecord:
        """Save a deep copy while preserving record identity on replacement."""

        key = str(run_id)
        existing = self._records.get(key)
        now = datetime.now(timezone.utc)
        if existing is None:
            record = CheckpointRecord(
                run_id=run_id,
                state=deepcopy(state),
                created_at=now,
                updated_at=now,
            )
        else:
            record = CheckpointRecord(
                id=existing.id,
                run_id=run_id,
                state=deepcopy(state),
                created_at=existing.created_at,
                updated_at=now,
            )
        self._records[key] = deepcopy(record)
        return deepcopy(record)

    def load(self, run_id: UUID) -> CheckpointRecord:
        """Return a deep copy of a checkpoint or raise when it is absent."""

        try:
            record = self._records[str(run_id)]
        except KeyError as error:
            raise CheckpointNotFoundError(
                f"checkpoint not found for run_id {run_id}"
            ) from error
        return deepcopy(record)

    def exists(self, run_id: UUID) -> bool:
        """Return whether a checkpoint is present for the run ID."""

        return str(run_id) in self._records

    def delete(self, run_id: UUID) -> bool:
        """Delete an existing checkpoint without failing when it is absent."""

        return self._records.pop(str(run_id), None) is not None
