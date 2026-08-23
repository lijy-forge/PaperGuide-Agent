"""Research task submission route."""

from fastapi import APIRouter, Depends, status

from paperpilot.application import ResearchRequest

from ..dependencies import APIDependencies, get_api_dependencies
from ..exceptions import APIError
from ..schemas import CreateResearchRequest, ErrorResponse, TaskAcceptedResponse

router = APIRouter(prefix="/research", tags=["research"])


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskAcceptedResponse,
    summary="Submit a research task",
    responses={
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def submit_research(
    payload: CreateResearchRequest,
    dependencies: APIDependencies = Depends(get_api_dependencies),
) -> TaskAcceptedResponse:
    """Enqueue work through the persistent Host client without executing it."""

    if len(payload.question) > dependencies.settings.max_question_length:
        raise APIError(
            "INVALID_REQUEST",
            "Research question exceeds the configured length limit.",
            422,
        )
    request = ResearchRequest(
        question=payload.question,
        max_papers=payload.max_papers,
        export_format=payload.export_format,
        manual_sources=list(payload.manual_sources),
    )
    handle = dependencies.task_host_client.submit(request)
    return TaskAcceptedResponse(
        task_id=handle.task_id,
        status=handle.status,
        created_at=handle.created_at,
    )
