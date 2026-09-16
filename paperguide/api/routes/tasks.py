"""Sanitized task status and cancellation routes."""

from uuid import UUID

from fastapi import APIRouter, Depends

from paperguide.application import ResearchTask, ResearchTaskStatus

from ..dependencies import APIDependencies, get_api_dependencies
from ..schemas import ErrorResponse, TaskStatusResponse

router = APIRouter(prefix="/tasks", tags=["tasks"])


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


def _error_code(task: ResearchTask) -> str | None:
    status = task.status
    if status is ResearchTaskStatus.FAILED:
        if task.error == "REPORT_QUALITY_REJECTED":
            return "REPORT_QUALITY_REJECTED"
        return "TASK_FAILED"
    if status is ResearchTaskStatus.DEAD_LETTER:
        return "TASK_DEAD_LETTER"
    return None
