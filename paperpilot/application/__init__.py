"""Public synchronous application service interface for PaperPilot."""

from .exceptions import ApplicationError, ResearchExecutionError, TaskNotFoundError
from .models import (
    ReportQualityStatus,
    ResearchRequest,
    ResearchResult,
    ResearchTask,
    ResearchTaskStatus,
)
from .service import (
    ReportExportServiceProtocol,
    ReportGeneratorProtocol,
    SurveyReportGeneratorProtocol,
    ResearchApplicationService,
    ResearchGraphProtocol,
)
from .store import InMemoryTaskStore, TaskStoreProtocol

__all__ = [
    "ApplicationError",
    "InMemoryTaskStore",
    "ReportExportServiceProtocol",
    "ReportGeneratorProtocol",
    "SurveyReportGeneratorProtocol",
    "ResearchApplicationService",
    "ResearchExecutionError",
    "ResearchGraphProtocol",
    "ResearchRequest",
    "ResearchResult",
    "ResearchTask",
    "ResearchTaskStatus",
    "ReportQualityStatus",
    "TaskNotFoundError",
    "TaskStoreProtocol",
]
