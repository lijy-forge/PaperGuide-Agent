"""Read-only JSON runtime metrics route."""

from fastapi import APIRouter, Depends

from ..dependencies import APIDependencies, get_api_dependencies
from ..exceptions import APIError
from ..schemas import ErrorResponse, MetricsResponse

router = APIRouter(tags=["runtime"])


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    summary="Get runtime metrics",
    responses={503: {"model": ErrorResponse}},
)
def get_metrics(
    dependencies: APIDependencies = Depends(get_api_dependencies),
) -> MetricsResponse:
    try:
        snapshot = dependencies.metrics_exporter.get_metrics()
    except Exception as error:
        raise APIError(
            "RUNTIME_NOT_READY",
            "Runtime metrics are unavailable.",
            503,
        ) from error
    return MetricsResponse.model_validate(snapshot.model_dump())
