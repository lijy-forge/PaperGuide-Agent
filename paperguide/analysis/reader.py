"""Evidence-grounded structured analysis of one parsed paper."""

from collections.abc import Iterable
from datetime import UTC, datetime

from paperguide.document import Document
from paperguide.domain import ExperimentSummary, MethodSummary
from paperguide.prompts import (
    PAPER_READER_PROMPT_VERSION,
    PAPER_READER_SYSTEM_PROMPT,
    build_paper_reader_user_prompt,
)

from .context_builder import PaperContextBuilder
from .evidence_mapper import EvidenceMapper
from .exceptions import (
    AnalysisLLMError,
    AnalysisSchemaValidationError,
    EvidenceMappingError,
    InsufficientEvidenceError,
    PaperAnalysisError,
    PaperContextError,
)
from .llm_protocol import StructuredLLMProtocol
from .models import (
    ExperimentAnalysis,
    PaperAnalysisResult,
    PaperReaderOutput,
)


class PaperReader:
    """Analyze one Document through injected context, LLM, and evidence services."""

    def __init__(
        self,
        llm: StructuredLLMProtocol,
        context_builder: PaperContextBuilder,
        evidence_mapper: EvidenceMapper,
    ):
        self.llm = llm
        self.context_builder = context_builder
        self.evidence_mapper = evidence_mapper

    def analyze(self, document: Document) -> PaperAnalysisResult:
        """Return a validated analysis or a typed PaperAnalysisError."""

        try:
            context = self.context_builder.build(document)
        except PaperContextError:
            raise
        except Exception as error:
            raise PaperContextError("unable to build paper context") from error

        try:
            output = self.llm.generate_structured(
                system_prompt=PAPER_READER_SYSTEM_PROMPT,
                user_prompt=build_paper_reader_user_prompt(context),
                response_model=PaperReaderOutput,
            )
            if not isinstance(output, PaperReaderOutput):
                output = PaperReaderOutput.model_validate(output)
        except AnalysisLLMError:
            raise
        except Exception as error:
            if self._is_validation_error(error):
                raise AnalysisSchemaValidationError(
                    "structured paper analysis returned an invalid schema"
                ) from error
            raise AnalysisLLMError("structured paper analysis invocation failed") from error

        try:
            mapping = self.evidence_mapper.map(output.evidence, document)
        except PaperAnalysisError:
            raise
        except Exception as error:
            raise EvidenceMappingError("unable to map paper evidence") from error

        method_ids, method_missing = self._resolve_keys(
            output.method.evidence_keys, mapping.key_to_id
        )
        if not method_ids:
            raise InsufficientEvidenceError(
                "critical method analysis has no valid mapped evidence"
            )
        experiment_keys = self._stable_unique(
            [
                *output.experiments.evidence_keys,
                *(
                    key
                    for metric in output.experiments.metrics
                    for key in metric.evidence_keys
                ),
            ]
        )
        experiment_ids, experiment_missing = self._resolve_keys(
            experiment_keys, mapping.key_to_id
        )

        warnings = [
            *context.warnings,
            *output.analysis_warnings,
            *mapping.warnings,
            *self._missing_key_warnings("method", method_missing),
            *self._missing_key_warnings("experiments", experiment_missing),
        ]
        if experiment_keys and not experiment_ids:
            warnings.append("Experiment analysis has no valid mapped evidence.")

        limitations = self._stable_unique(
            [*output.method.limitations, *output.limitations]
        )
        method_summary = MethodSummary(
            paper_id=document.paper_id,
            name=output.method.name,
            problem=output.method.problem or output.research_problem,
            summary=output.method.summary,
            innovations=output.method.innovations,
            limitations=limitations,
            evidence_ids=method_ids,
            confidence=output.method.confidence,
        )
        experiment_summary = ExperimentSummary(
            paper_id=document.paper_id,
            datasets=output.experiments.datasets,
            metrics=self._map_metrics(output.experiments),
            baselines=output.experiments.baselines,
            findings=output.experiments.findings,
            evidence_ids=experiment_ids,
            confidence=output.experiments.confidence,
        )

        return PaperAnalysisResult(
            paper_id=document.paper_id,
            document_id=document.id,
            paper_title=document.title,
            research_problem=output.research_problem,
            contributions=output.contributions,
            method_summary=method_summary,
            experiment_summary=experiment_summary,
            evidence=mapping.evidence,
            limitations=limitations,
            warnings=self._stable_unique(warnings),
            confidence=output.confidence,
            model_name=getattr(self.llm, "model_name", None),
            prompt_version=PAPER_READER_PROMPT_VERSION,
            analyzed_at=datetime.now(UTC),
        )

    @staticmethod
    def _resolve_keys(keys: list[str], key_to_id: dict) -> tuple[list, list[str]]:
        resolved = []
        missing: list[str] = []
        for key in keys:
            evidence_id = key_to_id.get(key)
            if evidence_id is None:
                missing.append(key)
            elif evidence_id not in resolved:
                resolved.append(evidence_id)
        return resolved, list(dict.fromkeys(missing))

    @staticmethod
    def _missing_key_warnings(area: str, keys: list[str]) -> list[str]:
        return [f"{area} references unknown or rejected evidence key {key!r}." for key in keys]

    @staticmethod
    def _map_metrics(experiments: ExperimentAnalysis) -> dict[str, str]:
        metrics: dict[str, str] = {}
        key_counts: dict[str, int] = {}
        for metric in experiments.metrics:
            base_key = (
                f"{metric.dataset}:{metric.metric}" if metric.dataset else metric.metric
            )
            key_counts[base_key] = key_counts.get(base_key, 0) + 1
            occurrence = key_counts[base_key]
            key = base_key if occurrence == 1 else f"{base_key}#{occurrence}"

            components: list[str] = []
            if metric.value is not None:
                components.append(metric.value)
            if metric.baseline is not None:
                components.append(f"baseline={metric.baseline}")
            if metric.comparison is not None:
                components.append(metric.comparison)
            metrics[key] = "; ".join(components)
        return metrics

    @staticmethod
    def _stable_unique(values: Iterable[str]) -> list[str]:
        return list(dict.fromkeys(value for value in values if value))

    @staticmethod
    def _is_validation_error(error: Exception) -> bool:
        from pydantic import ValidationError

        return isinstance(error, ValidationError)
