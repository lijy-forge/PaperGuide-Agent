"""Central construction of all PaperGuide runtime dependencies."""

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from paperguide.adapters import (
    ArxivClient,
    CrossrefClient,
    CrossrefConfig,
    OpenAlexClient,
    OpenAlexConfig,
    RetrieverProtocol,
    SemanticScholarClient,
    SemanticScholarConfig,
)
from paperguide.analysis import (
    EvidenceLinkingService,
    EvidenceMapper,
    PaperContextBuilder,
    PaperReader,
    StructuredLLMProtocol,
)
from paperguide.application import (
    InMemoryTaskStore,
    ResearchApplicationService,
    ResearchGraphProtocol,
    RetrieverAvailabilityProbe,
    TaskStoreProtocol,
)
from paperguide.document import (
    DocumentIngestionPipeline,
    DocumentTextCleaner,
    PdfDownloader,
    PdfParser,
)
from paperguide.export import (
    ExportService,
    ExportVerifier,
    HTMLExporter,
    MarkdownExporter,
    PDFExporter,
    PDFRendererProtocol,
)
from paperguide.integrations import GPTResearcherStructuredLLM
from paperguide.orchestration import create_research_graph
from paperguide.orchestration.concurrency import LLMCallLimiter
from paperguide.orchestration.nodes import (
    IngestionNode,
    PlannerNode,
    QualityGateNode,
    ReaderNode,
    RetrieverNode,
    VerifierNode,
)
from paperguide.pipeline import PaperSearchPipeline
from paperguide.progress.publisher import ProgressPublisherProtocol
from paperguide.relevance import (
    EvidenceAwareFinalRelevanceService,
    LLMQueryExpansionService,
    MetadataRelevanceGate,
    MultiQueryRetrievalService,
    QueryExpansionProtocol,
    ResearchIntentPlannerProtocol,
    RetrievalPlanService,
    StructuredLLMResearchIntentPlanner,
)
from paperguide.reporting import (
    EvidenceGroundedReportService,
    FullSurveySynthesisService,
    ProductionSurveyReportService,
    ReportContextBuilder,
    ReportVerifier,
    StructuredReportWriter,
    SurveyAnalysisDataBuilder,
    SurveyEvidenceDataBuilder,
    SurveyRenderService,
    SurveyReportContextBuilder,
    SurveySynthesisWriter,
    TaxonomyService,
)
from paperguide.services import PaperDeduplicator
from paperguide.usage import MeteredStructuredLLM, UsageLedger, resolve_prices
from paperguide.verification import (
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
    # Every LLM call in the pipeline goes through this one object, so wrapping
    # it here is what makes a run's consumption visible without touching each
    # call site. The ledger is per-container, therefore per-run.
    usage_ledger = UsageLedger(
        config_snapshot.model_name,
        resolve_prices(config_snapshot.model_name),
    )
    llm = MeteredStructuredLLM(llm, usage_ledger)

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
        # Built from the same retrievers the run will use, so the probe asks
        # the sources that matter. The offline demo's retriever answers it
        # without a network, which keeps one code path instead of two.
        source_probe=RetrieverAvailabilityProbe(selected_retrievers),
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
        usage_ledger=usage_ledger,
    )


def _default_retrievers() -> list[RetrieverProtocol]:
    """Build the automatic discovery sources used by hybrid mode.

    The four cover different literature. arXiv has preprints, so a field that
    publishes in journals is largely invisible through it. OpenAlex indexes the
    journals themselves and needs no key at all. Crossref is the DOI registry,
    so it reaches anything with a DOI, and it holds up when the others are
    refusing — on 2026-09-19 it answered while all three of the others were
    rate-limited at once. Semantic Scholar spans both, but its keyless rate
    limit is low enough to fail often, so it must not be the only source able
    to reach journal work.

    Source failures stay isolated in the search pipeline, so one unreachable
    source degrades the result instead of emptying it.
    """

    semantic_scholar_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    contact_email = os.environ.get("PAPERGUIDE_CONTACT_EMAIL", "").strip()
    return [
        ArxivClient(),
        OpenAlexClient(OpenAlexConfig(mailto=contact_email or None)),
        CrossrefClient(CrossrefConfig(mailto=contact_email or None)),
        SemanticScholarClient(
            SemanticScholarConfig(api_key=semantic_scholar_key or None)
        ),
    ]
