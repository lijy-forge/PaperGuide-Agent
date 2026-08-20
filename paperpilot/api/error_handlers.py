"""Central safe API exception mapping."""

import logging
import sqlite3
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from paperpilot.application import TaskNotFoundError
from paperpilot.execution import PersistentTaskStoreError
from paperpilot.runtime.host import SchemaMigrationError, TaskHostUnavailableError

from .exceptions import APIError
from .schemas import ErrorResponse

LOGGER = logging.getLogger("paperpilot.api")


def install_error_handlers(app: FastAPI) -> None:
    """Register stable error envelopes without exposing internal exceptions."""

    app.add_exception_handler(APIError, _api_error_handler)
    app.add_exception_handler(TaskNotFoundError, _task_not_found_handler)
    app.add_exception_handler(TaskHostUnavailableError, _host_unavailable_handler)
    app.add_exception_handler(PersistentTaskStoreError, _runtime_unavailable_handler)
    app.add_exception_handler(SchemaMigrationError, _runtime_unavailable_handler)
    app.add_exception_handler(sqlite3.Error, _runtime_unavailable_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(Exception, _internal_error_handler)


def _request_id(request: Request) -> UUID:
    return getattr(request.state, "request_id", uuid4())


def _response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    payload = ErrorResponse(
        code=code,
        message=message,
        request_id=_request_id(request),
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
    )


async def _api_error_handler(request: Request, error: APIError) -> JSONResponse:
    return _response(
        request,
        status_code=error.status_code,
        code=error.code,
        message=error.message,
    )


async def _task_not_found_handler(
    request: Request,
    error: TaskNotFoundError,
) -> JSONResponse:
    del error
    return _response(
        request,
        status_code=404,
        code="TASK_NOT_FOUND",
        message="Research task was not found.",
    )


async def _host_unavailable_handler(
    request: Request,
    error: TaskHostUnavailableError,
) -> JSONResponse:
    del error
    return _response(
        request,
        status_code=503,
        code="TASK_HOST_UNAVAILABLE",
        message="Research task host is unavailable.",
    )


async def _validation_error_handler(
    request: Request,
    error: RequestValidationError,
) -> JSONResponse:
    del error
    return _response(
        request,
        status_code=422,
        code="INVALID_REQUEST",
        message="Request validation failed.",
    )


async def _runtime_unavailable_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    del error
    return _response(
        request,
        status_code=503,
        code="RUNTIME_NOT_READY",
        message="Persistent runtime is unavailable.",
    )


async def _internal_error_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    settings = request.app.state.paperpilot_dependencies.settings
    LOGGER.error(
        "API request failed",
        extra={
            "request_id": str(_request_id(request)),
            "error_type": type(error).__name__,
        },
    )
    message = "Internal server error."
    if settings.expose_error_details:
        message = f"Internal server error ({type(error).__name__})."
    return _response(
        request,
        status_code=500,
        code="INTERNAL_ERROR",
        message=message,
    )
