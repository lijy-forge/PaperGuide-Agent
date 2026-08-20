"""Application container returned by the PaperPilot composition root."""

from dataclasses import dataclass

from paperpilot.application import (
    ResearchApplicationService,
    ResearchGraphProtocol,
    TaskStoreProtocol,
)
from paperpilot.export import ExportService
from paperpilot.reporting import EvidenceGroundedReportService, ProductionSurveyReportService
from paperpilot.relevance import RetrievalPlanService
from paperpilot.analysis import StructuredLLMProtocol

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
