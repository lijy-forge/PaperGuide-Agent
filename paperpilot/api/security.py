"""Request correlation, safe access logging, and response security headers."""

import logging
import time
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

LOGGER = logging.getLogger("paperpilot.api")
REQUEST_ID_HEADER = "X-Request-ID"


class APISecurityMiddleware(BaseHTTPMiddleware):
    """Apply local API security headers without reading request bodies."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = uuid4()
        request.state.request_id = request_id
        started = time.monotonic()
        response = await call_next(request)
        duration_ms = max(0.0, (time.monotonic() - started) * 1000)
        response.headers[REQUEST_ID_HEADER] = str(request_id)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        route = request.scope.get("route")
        route_template = getattr(route, "path", "unmatched")
        LOGGER.info(
            "API request completed",
            extra={
                "request_id": str(request_id),
                "method": request.method,
                "route": route_template,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response
