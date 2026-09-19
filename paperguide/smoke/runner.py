"""One-shot, cost-bounded execution of the real PaperGuide application graph."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from time import monotonic
from typing import Any, Protocol
from uuid import uuid4

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
from paperguide.application import (
    InMemoryTaskStore,
    ResearchApplicationService,
    ResearchRequest,
    ResearchResult,
    ResearchTaskStatus,
)
from paperguide.bootstrap import BootstrapConfig, create_application
from paperguide.domain import PaperSource
from paperguide.orchestration import ResearchState
from paperguide.orchestration.graph_factory import create_research_graph
from paperguide.runtime import RuntimeSettings

from .config import SmokeTestConfig
from .diagnostics import (
    StageRecorder,
    question_fingerprint,
    safe_artifact_filename,
    safe_diagnostic_message,
)
from .models import (
    SmokeStage,
    SmokeStageStatus,
    SmokeTestResult,
    SmokeTestStatus,
)


class SmokeApplicationProtocol(Protocol):
    """Minimum synchronous application boundary accepted by the smoke runner."""

    def run(self, request: ResearchRequest) -> ResearchResult:
        """Execute one complete research request."""

        ...


class ProviderNotConfiguredError(RuntimeError):
    """Raised before execution when a configured provider has no credentials."""


class _ObservedNode:
    def __init__(
        self,
        node: Callable[[ResearchState], ResearchState],
        recorder: StageRecorder,
        stages: Sequence[SmokeStage],
    ) -> None:
        self._node = node
        self._recorder = recorder
        self._stages = tuple(stages)

    def __call__(self, state: ResearchState) -> ResearchState:
        for stage in self._stages:
            self._recorder.start(stage)
        try:
            result = self._node(deepcopy(state))
        except Exception as error:
            for stage in self._stages:
                self._recorder.fail(stage, error)
            raise
        for stage in self._stages:
            self._recorder.succeed(stage, "existing workflow node completed")
        return result


class _CapturingGraph:
    def __init__(self, graph: Any) -> None:
        self._graph = graph
        self.state: ResearchState | None = None

    def invoke(self, state: ResearchState) -> ResearchState:
        result = self._graph.invoke(deepcopy(state))
        self.state = deepcopy(result)
        return result


class _ObservedReportService:
    def __init__(self, service: Any, recorder: StageRecorder) -> None:
        self._service = service
        self._recorder = recorder

    def generate(self, question: str, verified_results: list[Any]) -> Any:
        self._recorder.start(SmokeStage.REPORT_GENERATION)
        try:
            result = self._service.generate(question, deepcopy(verified_results))
        except Exception as error:
            self._recorder.fail(SmokeStage.REPORT_GENERATION, error)
            raise
        self._recorder.succeed(SmokeStage.REPORT_GENERATION)
        return result


class _ObservedExportService:
    def __init__(self, service: Any, recorder: StageRecorder) -> None:
        self._service = service
        self._recorder = recorder

    def export(self, report: Any, export_format: Any) -> Any:
        self._recorder.start(SmokeStage.ARTIFACT_EXPORT)
        try:
            result = self._service.export(report.model_copy(deep=True), export_format)
        except Exception as error:
            self._recorder.fail(SmokeStage.ARTIFACT_EXPORT, error)
            raise
        self._recorder.succeed(SmokeStage.ARTIFACT_EXPORT)
        return result


ApplicationFactory = Callable[
    [SmokeTestConfig, StageRecorder],
    tuple[SmokeApplicationProtocol, Callable[[], ResearchState | None]],
]


def check_provider_configuration(
    provider: str,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Check credential presence without reading or returning its value."""

    source = os.environ if environ is None else environ
    normalized = provider.strip().casefold().replace("-", "_")
    if normalized in {"ollama", "local", "lmstudio"}:
        return
    variables = {
        "openai": ("OPENAI_API_KEY",),
        "anthropic": ("ANTHROPIC_API_KEY",),
        "groq": ("GROQ_API_KEY",),
        "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
        "azure_openai": ("AZURE_OPENAI_API_KEY",),
    }.get(normalized, (f"{normalized.upper()}_API_KEY",))
    if not any(source.get(name, "").strip() for name in variables):
        raise ProviderNotConfiguredError(
            f"provider {normalized!r} has no configured credential environment variable"
        )


def create_real_smoke_application(
    config: SmokeTestConfig,
    recorder: StageRecorder,
    *,
    settings: RuntimeSettings | None = None,
) -> tuple[SmokeApplicationProtocol, Callable[[], ResearchState | None]]:
    """Compose existing production components with content-free observers."""

    runtime_settings = settings or RuntimeSettings.from_env()
    check_provider_configuration(runtime_settings.llm_provider)
    output_root = Path(config.output_directory)
    bootstrap = BootstrapConfig.model_validate(
        {
            **runtime_settings.to_bootstrap_config().model_dump(),
            "export_directory": output_root / "artifacts",
            "pdf_download": {
                **runtime_settings.to_bootstrap_config().pdf_download.model_dump(),
                "download_directory": output_root / "downloads",
                "timeout_seconds": min(config.timeout_seconds, 120.0),
            },
        }
    )
    retrievers: list[RetrieverProtocol] = []
    if PaperSource.ARXIV in config.sources:
        retrievers.append(ArxivClient())
    if PaperSource.CROSSREF in config.sources:
        retrievers.append(
            CrossrefClient(
                CrossrefConfig(
                    mailto=os.environ.get("PAPERGUIDE_CONTACT_EMAIL", "").strip()
                    or None
                )
            )
        )
    if PaperSource.OPENALEX in config.sources:
        retrievers.append(
            OpenAlexClient(
                # Same convention as the composition root: an unset or blank
                # variable means no mailto, not an empty one.
                OpenAlexConfig(
                    mailto=os.environ.get("PAPERGUIDE_CONTACT_EMAIL", "").strip()
                    or None
                )
            )
        )
    if PaperSource.SEMANTIC_SCHOLAR in config.sources:
        retrievers.append(
            SemanticScholarClient(
                SemanticScholarConfig(
                    api_key=os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
                )
            )
        )

    def observed_graph_factory(*nodes: Any) -> Any:
        planner, retriever, ingestion, reader, verifier, quality_gate = nodes
        return create_research_graph(
            planner,
            _ObservedNode(
                retriever,
                recorder,
                (SmokeStage.PAPER_RETRIEVAL, SmokeStage.METADATA_NORMALIZATION),
            ),
            _ObservedNode(
                ingestion,
                recorder,
                (SmokeStage.PDF_DOWNLOAD, SmokeStage.PDF_PARSE),
            ),
            _ObservedNode(
                reader,
                recorder,
                (SmokeStage.PAPER_READING, SmokeStage.EVIDENCE_MAPPING),
            ),
            _ObservedNode(verifier, recorder, (SmokeStage.EVIDENCE_VERIFICATION,)),
            quality_gate,
        )

    container = create_application(
        bootstrap,
        retrievers=retrievers,
        task_store=InMemoryTaskStore(),
        graph_factory=observed_graph_factory,
    )
    graph = _CapturingGraph(container.research_graph)
    application = ResearchApplicationService(
        graph,
        _ObservedReportService(container.report_service, recorder),
        _ObservedExportService(container.export_service, recorder),
        container.task_store,
        sources=config.sources,
    )
    return application, lambda: deepcopy(graph.state)


class SmokeTestRunner:
    """Run one real application request and persist only safe diagnostics."""

    def __init__(
        self,
        application_factory: ApplicationFactory = create_real_smoke_application,
    ) -> None:
        self._application_factory = application_factory

    def run(self, config: SmokeTestConfig) -> SmokeTestResult:
        """Execute once; this method never retries network or LLM operations."""

        snapshot = SmokeTestConfig.model_validate(config.model_dump())
        recorder = StageRecorder()
        started = monotonic()
        diagnostic_run_id = uuid4()
        state_provider: Callable[[], ResearchState | None] = lambda: None
        result: ResearchResult | None = None
        warning_messages: list[str] = []
        overall = SmokeTestStatus.FAILED

        try:
            recorder.start(SmokeStage.RUNTIME_CONFIGURATION)
            self._validate_output_directory(snapshot.output_directory)
            recorder.succeed(SmokeStage.RUNTIME_CONFIGURATION)

            recorder.start(SmokeStage.PROVIDER_INITIALIZATION)
            application, state_provider = self._application_factory(snapshot, recorder)
            recorder.succeed(SmokeStage.PROVIDER_INITIALIZATION)
            result = application.run(
                ResearchRequest(
                    question=snapshot.question,
                    max_papers=snapshot.max_papers,
                    export_format=snapshot.export_format,
                )
            )
            diagnostic_run_id = result.task.run_id
            if result.task.status is not ResearchTaskStatus.COMPLETED:
                raise RuntimeError(
                    f"smoke task ended with status {result.task.status.value}"
                )
            state = state_provider()
            verified_claims, rejected_claims = self._evidence_counts(state, result)
            if snapshot.require_verified_evidence and verified_claims == 0:
                raise RuntimeError("completed report contains no verified evidence")
            duration_ms = (monotonic() - started) * 1000
            if duration_ms > snapshot.timeout_seconds * 1000:
                raise TimeoutError("smoke execution exceeded configured timeout")
            overall = SmokeTestStatus.PASSED
        except Exception as error:
            self._mark_active_or_pending_failure(recorder, error)
            warning_messages.append(safe_diagnostic_message(error))
            state = state_provider()
            verified_claims, rejected_claims = self._evidence_counts(state, result)

        recorder.skip_pending("not reached because an earlier smoke stage failed")
        state = state_provider()
        papers = len(state.get("papers", [])) if state else 0
        documents = len(state.get("documents", {})) if state else 0
        report_generated = bool(result and result.report is not None)
        artifact = (
            safe_artifact_filename(result.export_result.file_path)
            if result and result.export_result
            else None
        )
        if result and result.export_result:
            warning_messages.extend(result.export_result.warnings)
        smoke_result = SmokeTestResult(
            run_id=diagnostic_run_id,
            question_fingerprint=question_fingerprint(snapshot.question),
            status=overall,
            stages=recorder.records(),
            retrieved_papers=papers,
            downloaded_documents=documents,
            parsed_documents=documents,
            verified_claims=verified_claims,
            rejected_claims=rejected_claims,
            report_generated=report_generated,
            artifact_filename=artifact,
            duration_ms=(monotonic() - started) * 1000,
            warnings=[safe_diagnostic_message(item) for item in warning_messages],
        )
        self._write_result(snapshot.output_directory, smoke_result)
        return smoke_result

    @staticmethod
    def _validate_output_directory(directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".paperguide-smoke-", dir=directory)
        os.close(descriptor)
        Path(name).unlink()

    @staticmethod
    def _mark_active_or_pending_failure(
        recorder: StageRecorder,
        error: Exception,
    ) -> None:
        if any(
            recorder.status(stage) is SmokeStageStatus.FAILED
            for stage in SmokeStage
        ):
            return
        for stage in SmokeStage:
            if recorder.status(stage) is SmokeStageStatus.RUNNING:
                recorder.fail(stage, error)
                return
        for stage in SmokeStage:
            if recorder.status(stage) is SmokeStageStatus.PENDING:
                recorder.start(stage)
                recorder.fail(stage, error)
                return

    @staticmethod
    def _evidence_counts(
        state: ResearchState | None,
        result: ResearchResult | None,
    ) -> tuple[int, int]:
        if state:
            verifications = state.get("verification_results", {}).values()
            return (
                sum(
                    item.total_verified + item.total_partial
                    for item in verifications
                ),
                sum(
                    item.total_rejected + item.total_conflicted
                    for item in verifications
                ),
            )
        if result and result.report:
            return len(result.report.evidence_ids), 0
        return 0, 0

    @staticmethod
    def _write_result(directory: Path, result: SmokeTestResult) -> None:
        target = directory / "smoke-result.json"
        payload = result.model_dump_json(indent=2).encode("utf-8")
        descriptor, name = tempfile.mkstemp(
            prefix=".smoke-result-",
            suffix=".tmp",
            dir=directory,
        )
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
