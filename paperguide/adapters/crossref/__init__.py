"""Crossref adapter: the DOI registry, no key, journal coverage."""

from .client import (
    CrossrefClient,
    CrossrefConfig,
    CrossrefError,
    CrossrefInvalidResponseError,
    CrossrefNetworkError,
)
from .mapper import CrossrefMapper

__all__ = [
    "CrossrefClient",
    "CrossrefConfig",
    "CrossrefError",
    "CrossrefInvalidResponseError",
    "CrossrefMapper",
    "CrossrefNetworkError",
]
