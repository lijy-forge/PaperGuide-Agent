"""Central construction of all PaperPilot runtime dependencies."""

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from paperpilot.adapters import (
    ArxivClient,
    RetrieverProtocol,
    SemanticScholarClient,
    SemanticScholarConfig,
)
from paperpilot.analysis import (
    EvidenceMapper,
    PaperContextBuilder,
    PaperReader,
    EvidenceLinkingService,
    StructuredLLMProtocol,
)
from paperpilot.application import (
    InMemoryTaskStore,
    ResearchApplicationService,
    ResearchGraphProtocol,
    TaskStoreProtocol,
)
from paperpilot.document import (
    DocumentIngestionPipeline,
    DocumentTextCleaner,
    PdfDownloader,
    PdfParser,
)
from paperpilot.export import (
    ExportService,
    ExportVerifier,
    HTMLExporter,
    MarkdownExporter,
    PDFExporter,
    PDFRendererProtocol,
)
from paperpilot.integrations import GPTResearcherStructuredLLM
from paperpilot.orchestration import create_research_graph
from paperpilot.orchestration.concurrency import LLMCallLimiter
from paperpilot.orchestration.nodes import (
    IngestionNode,
    PlannerNode,
    QualityGateNode,
    ReaderNode,
    RetrieverNode,
    VerifierNode,
)
from paperpilot.pipeline import PaperSearchPipeline
from paperpilot.reporting import (
    EvidenceGroundedReportService,
    FullSurveySynthesisService,
    ProductionSurveyReportService,
    ReportContextBuilder,
    ReportVerifier,
    SurveyAnalysisDataBuilder,
    SurveyEvidenceDataBuilder,
    SurveyRenderService,
    SurveyReportContextBuilder,
    SurveySynthesisWriter,
    StructuredReportWriter,
    TaxonomyService,
)
from paperpilot.relevance import (
    LLMQueryExpansionService,
    QueryExpansionProtocol,
    ResearchIntentPlannerProtocol,
    RetrievalPlanService,
    StructuredLLMResearchIntentPlanner,
    MetadataRelevanceGate,
    MultiQueryRetrievalService,
    EvidenceAwareFinalRelevanceService,
)
from paperpilot.services import PaperDeduplicator
from paperpilot.progress.publisher import ProgressPublisherProtocol
from paperpilot.verification import (
    DeterministicEvidenceChecker,
    EvidenceConflictDetector,
    EvidenceVerifier,
    LLMEvidenceVerifier,
)

from .config import BootstrapConfig
from .container import ApplicationContainer
from .exceptions import BootstrapError

GraphFactory = Callable[
    [
        PlannerNode,
        RetrieverNode,
        IngestionNode,
        ReaderNode,
        VerifierNode,
        QualityGateNode,
    ],
    ResearchGraphProtocol,
]


@dataclass(frozen=True, slots=True)
class _GPTResearcherLLMSettings:
    """Minimal non-secret configuration consumed by the host LLM adapter."""

    smart_llm_provider: str
    smart_llm_model: str
    smart_token_limit: int
    llm_kwargs: dict[str, object] = field(default_factory=dict)


def create_application(
    config: BootstrapConfig,
    *,
    structured_llm: StructuredLLMProtocol | None = None,
    retrievers: Sequence[RetrieverProtocol] | None = None,
    task_store: TaskStoreProtocol | None = None,
    pdf_opener: Callable[..., Any] | None = None,
    pymupdf_module: Any | None = None,
    pdf_renderer: PDFRendererProtocol | None = None,
    graph_factory: GraphFactory = create_research_graph,
    intent_planner: ResearchIntentPlannerProtocol | None = None,
    query_expander: QueryExpansionProtocol | None = None,
    progress_publisher: ProgressPublisherProtocol | None = None,
) -> ApplicationContainer:
    """Build one complete dependency graph without performing external I/O.

    Optional arguments are boundary-level test seams. Supplying them replaces only
    the corresponding external dependency; services, nodes, and their wiring remain
    centralized in this composition root.
    """

    if not isinstance(config, BootstrapConfig):
        raise BootstrapError("config must be a BootstrapConfig instance")
    config_snapshot = BootstrapConfig.model_validate(config.model_dump())

    selected_retrievers = (
        _default_retrievers() if retrievers is None else list(retrievers)
    )
    if not selected_retrievers:
        raise BootstrapError("at least one retriever must be configured")

    llm = (
        structured_llm
        if structured_llm is not None
        else GPTResearcherStructuredLLM(
            _GPTResearcherLLMSettings(
                smart_llm_provider=config_snapshot.llm_provider.provider,
                smart_llm_model=config_snapshot.model_name,
                smart_token_limit=config_snapshot.llm_provider.max_tokens,
                llm_kwargs={
                    "request_timeout": config_snapshot.llm_provider.request_timeout_seconds
                },
            )
        )
    )
    retrieval_plan_service = RetrievalPlanService(
        intent_planner or StructuredLLMResearchIntentPlanner(llm),
        query_expander or LLMQueryExpansionService(llm),
    )

    deduplicator = PaperDeduplicator()
    search_pipeline = PaperSearchPipeline(selected_retrievers, deduplicator)
    multi_query_service = MultiQueryRetrievalService(
        search_pipeline,
        deduplicator=deduplicator,
        gate=MetadataRelevanceGate(),
    )

    pdf_config = config_snapshot.pdf_download
    downloader = PdfDownloader(
        pdf_config.download_directory,
        timeout_seconds=pdf_config.timeout_seconds,
        max_size_bytes=pdf_config.max_size_bytes,
        user_agent=pdf_config.user_agent,
        opener=pdf_opener,
        manual_source_dir=pdf_config.download_directory.parent / "manual-sources",
    )
    parser = PdfParser(pymupdf_module)
    cleaner = DocumentTextCleaner()
    ingestion_pipeline = DocumentIngestionPipeline(downloader, parser, cleaner)

    paper_context_builder = PaperContextBuilder()
    evidence_mapper = EvidenceMapper()
    paper_reader = PaperReader(llm, paper_context_builder, evidence_mapper)

    deterministic_checker = DeterministicEvidenceChecker()
    llm_evidence_verifier = LLMEvidenceVerifier(llm)
    conflict_detector = EvidenceConflictDetector()
    evidence_verifier = EvidenceVerifier(
        llm_evidence_verifier,
        deterministic_checker,
        conflict_detector,
    )

    report_context_builder = ReportContextBuilder(
        max_context_chars=config_snapshot.report_max_context_chars
    )
    report_writer = StructuredReportWriter(llm)
    report_verifier = ReportVerifier()
    report_service = EvidenceGroundedReportService(
        report_context_builder,
        report_writer,
        report_verifier,
    )
    survey_report_service = ProductionSurveyReportService(
        SurveyEvidenceDataBuilder(),
        SurveyAnalysisDataBuilder(taxonomy_service=TaxonomyService(llm)),
        SurveyReportContextBuilder(),
        FullSurveySynthesisService(SurveySynthesisWriter(llm)),
    )

    export_verifier = ExportVerifier()
    markdown_exporter = MarkdownExporter(export_verifier)
    html_exporter = HTMLExporter(export_verifier)
    pdf_exporter = PDFExporter(renderer=pdf_renderer, verifier=export_verifier)
    export_service = ExportService(
        config_snapshot.export_directory,
        verifier=export_verifier,
        markdown_exporter=markdown_exporter,
        html_exporter=html_exporter,
        pdf_exporter=pdf_exporter,
        survey_renderer=SurveyRenderService(),
    )

    planner_node = PlannerNode(retrieval_plan_service, progress_publisher)
    retriever_node = RetrieverNode(
        search_pipeline,
        plan_service=retrieval_plan_service,
        multi_query_service=multi_query_service,
        progress_publisher=progress_publisher,
    )
    ingestion_node = IngestionNode(
        ingestion_pipeline,
        progress_publisher,
        max_concurrency=config_snapshot.orchestrator_config.max_paper_concurrency,
    )
    llm_limiter = LLMCallLimiter(
        config_snapshot.orchestrator_config.max_paper_concurrency
    )
    reader_node = ReaderNode(
        paper_reader,
        progress_publisher,
        max_concurrency=config_snapshot.orchestrator_config.max_paper_concurrency,
        llm_limiter=llm_limiter,
    )
    verifier_node = VerifierNode(
        evidence_verifier,
        final_relevance_service=EvidenceAwareFinalRelevanceService(),
        evidence_linking_service=EvidenceLinkingService(),
        progress_publisher=progress_publisher,
        max_concurrency=config_snapshot.orchestrator_config.max_paper_concurrency,
        llm_limiter=llm_limiter,
    )
    quality_gate_node = QualityGateNode(config_snapshot.orchestrator_config)
    try:
        research_graph = graph_factory(
            planner_node,
            retriever_node,
            ingestion_node,
            reader_node,
            verifier_node,
            quality_gate_node,
        )
    except Exception as error:
        raise BootstrapError("research graph assembly failed") from error
    if not callable(getattr(research_graph, "invoke", None)):
        raise BootstrapError("graph factory returned an incompatible graph")

    selected_task_store = (
        task_store if task_store is not None else InMemoryTaskStore()
    )
    application_service = ResearchApplicationService(
        research_graph,
        report_service,
        export_service,
        selected_task_store,
        survey_report_generator=survey_report_service,
        progress_publisher=progress_publisher,
    )
    return ApplicationContainer(
        application_service=application_service,
        research_graph=research_graph,
        report_service=report_service,
        survey_report_service=survey_report_service,
        export_service=export_service,
        task_store=selected_task_store,
        config=config_snapshot,
        retrieval_plan_service=retrieval_plan_service,
        structured_llm=llm,
    )


def _default_retrievers() -> list[RetrieverProtocol]:
    """Build the two automatic discovery sources used by hybrid mode.

    arXiv and Semantic Scholar are always attempted.  A Semantic Scholar API
    key is optional and raises its rate limit; source failures remain isolated
    by the search pipeline so arXiv can still produce a degraded result.
    """

    semantic_scholar_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    return [
        ArxivClient(),
        SemanticScholarClient(
            SemanticScholarConfig(api_key=semantic_scholar_key or None)
        ),
    ]
