"""Public domain models for PaperGuide AI."""

from .author import Author
from .enums import EvidenceType, FullTextStatus, PaperSource
from .evidence import Evidence, SourceLocator
from .experiment import ExperimentSummary
from .method import MethodSummary
from .manual_source import ManualPaperSource
from .paper import PaperCandidate
from .research import ResearchConfig

__all__ = [
    "Author",
    "Evidence",
    "EvidenceType",
    "ExperimentSummary",
    "FullTextStatus",
    "MethodSummary",
    "ManualPaperSource",
    "PaperCandidate",
    "PaperSource",
    "ResearchConfig",
    "SourceLocator",
]
