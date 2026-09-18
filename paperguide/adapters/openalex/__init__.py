"""OpenAlex adapter: journal-indexed metadata without an API key."""

from .client import (
    OpenAlexClient,
    OpenAlexConfig,
    OpenAlexError,
    OpenAlexInvalidResponseError,
    OpenAlexNetworkError,
)
from .mapper import OpenAlexMapper

__all__ = [
    "OpenAlexClient",
    "OpenAlexConfig",
    "OpenAlexError",
    "OpenAlexInvalidResponseError",
    "OpenAlexMapper",
    "OpenAlexNetworkError",
]
