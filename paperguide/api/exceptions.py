"""Typed safe exceptions exposed by the HTTP boundary."""


class APIError(RuntimeError):
    """Expected API failure with a stable public code and HTTP status."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
