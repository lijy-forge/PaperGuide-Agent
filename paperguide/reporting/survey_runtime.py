"""Production bridge from a completed research state to a SurveyReport."""

from copy import deepcopy
import inspect
import re

from paperguide.orchestration import ResearchState, validate_state
from paperguide.relevance import ReportMode

from .analysis_data import SurveyAnalysisDataBuilder
from .citations import SurveyEvidenceDataBuilder
from .exceptions import ReportGenerationError
from .survey import LiteratureMethodFacts, SurveyReport, SurveyReportContextBuilder
from .synthesis import FullSurveySynthesisService
from .survey_telemetry import NullSurveyTelemetry, SurveyTelemetryProtocol


class ProductionSurveyReportService:
    """Generate the production survey directly from verified graph state."""

    def __init__(
        self,
        evidence_builder: SurveyEvidenceDataBuilder,
        analysis_builder: SurveyAnalysisDataBuilder,
        context_builder: SurveyReportContextBuilder,
        synthesis_service: FullSurveySynthesisService,
        *,
        deterministic_analysis: bool = False,
    ) -> None:
        self.evidence_builder = evidence_builder
        self.analysis_builder = analysis_builder
        self.context_builder = context_builder
        self.synthesis_service = synthesis_service
        self.deterministic_analysis = deterministic_analysis

    def generate(
        self,
        state: ResearchState,
        *,
        telemetry: SurveyTelemetryProtocol | None = None,
    ) -> SurveyReport:
        """Use the report mode selected by evidence sufficiency, without fallback."""

        observer = telemetry or NullSurveyTelemetry()
        observer.stage_started()
        try:
            final_state = validate_state(deepcopy(state))
            sufficiency = final_state.get("evidence_sufficiency")
            mode = (
                sufficiency.recommended_report_mode
                if sufficiency is not None
                else final_state.get("report_mode")
            )
            if not isinstance(mode, ReportMode):
                raise ReportGenerationError("SURVEY_REPORT_GENERATION_FAILED: missing report mode")
            evidence_started = observer.substage_started("evidence_data")
            try:
                evidence = self.evidence_builder.build_from_state(final_state)
            except Exception as error:
                observer.substage_failed("evidence_data", evidence_started, error)
                raise
            observer.update_input_counts(
                input_paper_count=len(evidence.core_paper_profiles),
                input_statement_count=len(evidence.evidence_ledger),
                citation_capable_statement_count=len({item.statement_key for item in evidence.evidence_ledger}),
                core_paper_count=len(evidence.core_paper_profiles),
                registered_citation_count=len(evidence.citation_registry),
            )
            observer.substage_completed("evidence_data", evidence_started)
            analysis_started = observer.substage_started("analysis_data")
            try:
                analysis = self.analysis_builder.build(
                    evidence,
                    final_state["papers"],
                    final_state.get("evidence_linked_analysis", {}),
                    final_state["verified_results"],
                    mode,
                    deterministic=self.deterministic_analysis,
                    telemetry=observer,
                )
            except Exception as error:
                observer.substage_failed("analysis_data", analysis_started, error)
                raise
            observer.update_input_counts(
                taxonomy_family_count=len(analysis.taxonomy.taxonomy),
                comparison_row_count=len(analysis.comparison_matrix.rows),
            )
            observer.substage_completed("analysis_data", analysis_started)
            facts = LiteratureMethodFacts.from_state(final_state)
            plan = final_state.get("retrieval_plan")
            intent = getattr(plan, "intent", None)
            context_started = observer.substage_started("survey_context")
            try:
                context = self.context_builder.build(
                    final_state["question"],
                    evidence,
                    mode,
                    facts,
                    query_language=getattr(intent, "query_language", None),
                )
            except Exception as error:
                observer.substage_failed("survey_context", context_started, error)
                raise
            observer.substage_completed("survey_context", context_started)
            synthesis_started = observer.substage_started("synthesis")
            try:
                generate = self.synthesis_service.generate
                if "telemetry" in inspect.signature(generate).parameters:
                    report = generate(
                        context, evidence, analysis, facts, telemetry=observer
                    ).model_copy(deep=True)
                else:
                    report = generate(
                        context, evidence, analysis, facts
                    ).model_copy(deep=True)
            except Exception as error:
                observer.substage_failed("synthesis", synthesis_started, error)
                raise
            observer.substage_completed("synthesis", synthesis_started)
            observer.stage_completed()
            return report
        except ReportGenerationError as error:
            observer.stage_aborted(error)
            raise
        except Exception as error:
            observer.stage_aborted(error)
            raise ReportGenerationError(self._safe_failure_code(error)) from error

    @staticmethod
    def _safe_failure_code(error: Exception) -> str:
        """Preserve diagnostic types/codes without publishing report content."""

        types: list[str] = []
        explicit_code: str | None = None
        current: BaseException | None = error
        while current is not None and len(types) < 5:
            types.append(type(current).__name__)
            message = str(current).strip()
            if re.fullmatch(r"[A-Z][A-Z0-9_:-]{2,120}", message):
                explicit_code = message
            current = current.__cause__
        details = ":".join(types)
        if explicit_code:
            details += f":{explicit_code}"
        return f"SURVEY_REPORT_GENERATION_FAILED:{details}"
