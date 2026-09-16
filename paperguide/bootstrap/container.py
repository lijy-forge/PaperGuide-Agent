"""Application container returned by the PaperGuide composition root."""

from dataclasses import dataclass

from paperguide.analysis import StructuredLLMProtocol
from paperguide.application import (
    ResearchApplicationService,
    ResearchGraphProtocol,
    TaskStoreProtocol,
)
from paperguide.export import ExportService
from paperguide.relevance import RetrievalPlanService
from paperguide.reporting import EvidenceGroundedReportService, ProductionSurveyReportService

from .config import BootstrapConfig


@dataclass(frozen=True, slots=True)
class ApplicationContainer:
    """Hold one fully assembled and internally consistent application object graph."""

    application_service: ResearchApplicationService
    research_graph: ResearchGraphProtocol
    report_service: EvidenceGroundedReportService
    survey_report_service: ProductionSurveyReportService
    export_service: ExportService
    task_store: TaskStoreProtocol
    config: BootstrapConfig
    retrieval_plan_service: RetrievalPlanService
    structured_llm: StructuredLLMProtocol
