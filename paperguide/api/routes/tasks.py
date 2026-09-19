"""Sanitized task status and cancellation routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from paperguide.application import ResearchTask, ResearchTaskStatus

from ..dependencies import APIDependencies, get_api_dependencies
from ..schemas import ErrorResponse, TaskListResponse, TaskStatusResponse

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get(
    "",
    response_model=TaskListResponse,
    summary="List research tasks, newest first",
)
def list_tasks(
    status: ResearchTaskStatus | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    dependencies: APIDependencies = Depends(get_api_dependencies),
) -> TaskListResponse:
    """Page through task history, optionally filtered to one status.

    Without this the only way to reach a task was to already know its id, so a
    client could show the counters — two failed, one dead-lettered — and offer
    no way to open any of them. The dashboard kept its own list in browser
    storage, which meant history was per-browser and never matched the totals.
    """

    tasks, total = dependencies.task_host_client.list_tasks(
        limit=limit, offset=offset, status=status
    )
    return TaskListResponse(
        items=[task_response(task) for task in tasks],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{task_id}",
    response_model=TaskStatusResponse,
    summary="Get research task status",
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def get_task_status(
    task_id: UUID,
    dependencies: APIDependencies = Depends(get_api_dependencies),
) -> TaskStatusResponse:
    task = dependencies.task_host_client.get_status(task_id)
    return task_response(task)


@router.post(
    "/{task_id}/cancel",
    response_model=TaskStatusResponse,
    summary="Request idempotent task cancellation",
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def cancel_task(
    task_id: UUID,
    dependencies: APIDependencies = Depends(get_api_dependencies),
) -> TaskStatusResponse:
    task = dependencies.task_host_client.cancel(task_id)
    return task_response(task)


def task_response(task: ResearchTask) -> TaskStatusResponse:
    """Map internal state without exposing question, error text, or file path."""

    status = task.status
    artifact = task.artifact
    return TaskStatusResponse(
        task_id=task.task_id,
        run_id=task.run_id,
        status=status,
        created_at=task.created_at,
        updated_at=task.updated_at,
        artifact_available=(
            status is ResearchTaskStatus.COMPLETED and artifact is not None
        ),
        artifact_format=artifact.format if artifact is not None else None,
        human_review_required=status is ResearchTaskStatus.HUMAN_REVIEW,
        retryable=status is ResearchTaskStatus.FAILED,
        error_code=_error_code(task),
    )


#: Failure reasons safe to pass through: each names a contract the run broke,
#: with no exception type, question text or path in it. Anything else collapses
#: to TASK_FAILED rather than risking an internal message reaching a client.
_PUBLIC_ERROR_CODES = frozenset(
    {
        "REPORT_QUALITY_REJECTED",
        "NO_EVIDENCE_FOR_QUESTION",
        "NO_PAPERS_IN_TIME_RANGE",
    }
)


def _error_code(task: ResearchTask) -> str | None:
    status = task.status
    if status is ResearchTaskStatus.FAILED:
        if task.error in _PUBLIC_ERROR_CODES:
            return task.error
        return "TASK_FAILED"
    if status is ResearchTaskStatus.DEAD_LETTER:
        return "TASK_DEAD_LETTER"
    return None
