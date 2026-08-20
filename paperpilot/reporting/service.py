"""Composed evidence-grounded report generation service."""

from copy import deepcopy
from typing import overload

from paperpilot.orchestration import ResearchState, validate_state
from paperpilot.orchestration.errors import StateValidationError
from paperpilot.verification import VerifiedPaperAnalysisResult

from .context import ReportContextBuilder
from .exceptions import (
    ReportContextBuildError,
    ReportGenerationError,
    ReportVerificationError,
    ReportWritingError,
)
from .models import ResearchReport
from .verifier import ReportVerifier
from .writer import StructuredReportWriter


class EvidenceGroundedReportService:
    """Compose context building, structured writing, and report verification."""

    def __init__(
        self,
        context_builder: ReportContextBuilder,
        writer: StructuredReportWriter,
        verifier: ReportVerifier,
    ) -> None:
        self.context_builder = context_builder
        self.writer = writer
        self.verifier = verifier

    @overload
    def generate(self, state: ResearchState) -> ResearchReport:
        """Generate a report from a complete orchestration state."""

    @overload
    def generate(
        self,
        state: str,
        verified_results: list[VerifiedPaperAnalysisResult],
    ) -> ResearchReport:
        """Support the existing application protocol without changing it."""

    def generate(
        self,
        state: ResearchState | str,
        verified_results: list[VerifiedPaperAnalysisResult] | None = None,
    ) -> ResearchReport:
        """Return a verified report through injected deterministic boundaries."""

        if isinstance(state, str):
            question = state.strip()
            results = verified_results
            if not question:
                raise ReportGenerationError("report question must not be empty")
            if results is None:
                raise ReportGenerationError("verified_results are required")
        else:
            try:
                validated_state = validate_state(deepcopy(state))
            except StateValidationError as error:
                raise ReportGenerationError(
                    "research state is invalid for report generation"
                ) from error
            question = validated_state["question"]
            results = list(validated_state["verified_results"].values())

        if not results:
            raise ReportContextBuildError(
                "verified_results must contain at least one paper"
            )

        try:
            context = self.context_builder.build(deepcopy(results))
        except ReportContextBuildError:
            raise
        except Exception as error:
            raise ReportContextBuildError(
                "unable to build report context from verified results"
            ) from error

        try:
            report = self.writer.write(question, context.model_copy(deep=True))
        except ReportWritingError:
            raise
        except Exception as error:
            raise ReportWritingError(
                "unable to write a structured research report"
            ) from error

        try:
            verified_report = self.verifier.verify(
                report.model_copy(deep=True),
                context.model_copy(deep=True),
            )
        except ReportVerificationError:
            raise
        except Exception as error:
            raise ReportVerificationError(
                "unable to verify research report evidence"
            ) from error
        return verified_report.model_copy(deep=True)
