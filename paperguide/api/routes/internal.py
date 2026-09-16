"""Loopback-only internal diagnostics; never included in public API contracts."""

from fastapi import APIRouter, Depends, Request

from paperguide.runtime.host import ProviderPreflightResult, TaskHostUnavailableError

from ..dependencies import APIDependencies, get_api_dependencies
from ..exceptions import APIError

router = APIRouter(
    prefix="/internal/provider",
    tags=["internal"],
    include_in_schema=False,
)

_LOOPBACK_CLIENTS = {"127.0.0.1", "::1", "localhost", "testclient"}
_WAIT_TIMEOUT_SECONDS = 190.0


@router.post(
    "/preflight",
    response_model=ProviderPreflightResult,
    summary="Explicitly verify the active TaskHost provider connection",
)
def provider_preflight(
    request: Request,
    dependencies: APIDependencies = Depends(get_api_dependencies),
) -> ProviderPreflightResult:
    """Queue one safe probe which is executed only by the running TaskHost."""

    client = request.client
    if client is None or client.host not in _LOOPBACK_CLIENTS:
        raise APIError(
            status_code=404,
            code="NOT_FOUND",
            message="Not found.",
        )
    if not dependencies.broker.host_available():
        raise TaskHostUnavailableError("persistent task host is unavailable")
    request_id = dependencies.broker.enqueue_provider_preflight()
    result = dependencies.broker.wait_provider_preflight(
        request_id,
        timeout_seconds=_WAIT_TIMEOUT_SECONDS,
    )
    if result is None:
        raise APIError(
            status_code=504,
            code="PROVIDER_PREFLIGHT_PENDING",
            message="Provider preflight did not finish in time.",
        )
    return result
