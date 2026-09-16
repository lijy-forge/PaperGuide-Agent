"""Paginated content-free task event query route."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from paperguide.runtime.host import TaskEventType

from ..dependencies import APIDependencies, get_api_dependencies
from ..schemas import ErrorResponse, TaskEventResponse

router = APIRouter(prefix="/tasks", tags=["events"])


@router.get(
    "/{task_id}/events",
    response_model=list[TaskEventResponse],
    summary="List task runtime events",
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def list_task_events(
    task_id: UUID,
    limit: int = Query(default=20, ge=1),
    offset: int = Query(default=0, ge=0),
    after_id: int | None = Query(default=None, ge=0),
    event_type: TaskEventType | None = Query(default=None),
    dependencies: APIDependencies = Depends(get_api_dependencies),
) -> list[TaskEventResponse]:
    if limit > dependencies.settings.max_event_page_size:
        from ..exceptions import APIError

        raise APIError(
            "INVALID_REQUEST",
            "Event page size exceeds the configured maximum.",
            422,
        )
    dependencies.task_store.get(task_id)
    events = dependencies.broker.list_events(
        task_id,
        limit=limit,
        offset=offset,
        after_id=after_id,
        event_type=event_type,
    )
    return [
        TaskEventResponse(
            event_id=event.event_id,
            event_type=event.event_type,
            status=event.status,
            attempt_count=event.attempt_count,
            duration_ms=event.duration_ms,
            created_at=event.created_at,
            progress=event.progress,
        )
        for event in events
    ]
