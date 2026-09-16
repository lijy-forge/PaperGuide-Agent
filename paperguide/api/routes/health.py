"""API liveness and runtime readiness routes."""

from fastapi import APIRouter, Depends, Response

from ..dependencies import APIDependencies, get_api_dependencies
from ..schemas import HealthResponse

router = APIRouter(tags=["runtime"])


@router.get(
    "/health/live",
    response_model=HealthResponse,
    summary="Check API process liveness",
)
def liveness() -> HealthResponse:
    return HealthResponse(
        kind="liveness",
        status="healthy",
        ready=True,
        checks=[],
    )


@router.get(
    "/health/ready",
    response_model=HealthResponse,
    summary="Check runtime readiness",
    responses={503: {"model": HealthResponse}},
)
def readiness(
    response: Response,
    dependencies: APIDependencies = Depends(get_api_dependencies),
) -> HealthResponse:
    try:
        report = dependencies.runtime_health_checker.check()
    except Exception:
        report = HealthResponse(
            kind="readiness",
            status="unhealthy",
            ready=False,
            checks=[],
        )
    if not report.ready:
        response.status_code = 503
    return report
