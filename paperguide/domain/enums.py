"""Enumerations shared by PaperGuide domain models."""

from enum import Enum


class PaperSource(str, Enum):
    """Supported sources from which a paper can be discovered."""

    ARXIV = "arxiv"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    OPENALEX = "openalex"
    CROSSREF = "crossref"
    PUBMED_CENTRAL = "pubmed_central"
    WEB = "web"
    GOOGLE_SCHOLAR = "google_scholar"
    CNKI = "cnki"
    USER_UPLOAD = "user_upload"


class FullTextStatus(str, Enum):
    """Availability state of a paper's full text."""

    UNKNOWN = "unknown"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class EvidenceType(str, Enum):
    """Relationship between an extracted fact and its supporting source."""

    DIRECT = "direct"
    DERIVED = "derived"
    INFERENCE = "inference"
    UNSUPPORTED = "unsupported"
