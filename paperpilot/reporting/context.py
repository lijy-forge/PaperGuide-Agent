"""Deterministic bounded context construction from verified paper analyses."""

import json
from copy import deepcopy

from paperpilot.verification import (
    VerificationStatus,
    VerifiedPaperAnalysisResult,
)

from .exceptions import ReportContextError
from .models import ReportContext, ReportEvidenceContext, ReportPaperContext


class ReportContextBuilder:
    """Select accepted evidence and serialize it within a character budget."""

    def __init__(self, max_context_chars: int = 30_000) -> None:
        if max_context_chars < 1:
            raise ReportContextError("max_context_chars must be positive")
        self.max_context_chars = max_context_chars

    def build(self, results: list[VerifiedPaperAnalysisResult]) -> ReportContext:
        """Return a bounded context without mutating verified result objects."""

        candidates: list[ReportEvidenceContext] = []
        paper_candidates: list[ReportPaperContext] = []
        warnings: list[str] = []
        seen_ids = set()
        for result in results:
            accepted_ids = set(result.verification.accepted_evidence_ids)
            warnings.extend(result.warnings)
            method = result.verified_method_summary
            experiment = result.verified_experiment_summary
            retained_ids = list(
                dict.fromkeys([*method.evidence_ids, *experiment.evidence_ids])
            )
            paper_candidates.append(
                ReportPaperContext(
                    paper_id=result.original_analysis.paper_id,
                    title=result.original_analysis.paper_title,
                    research_problem=result.original_analysis.research_problem,
                    method_name=method.name,
                    method_problem=method.problem,
                    method_summary=method.summary,
                    innovations=list(method.innovations),
                    limitations=list(result.verified_limitations or method.limitations),
                    datasets=list(experiment.datasets),
                    metrics=dict(experiment.metrics),
                    baselines=list(experiment.baselines),
                    findings=list(experiment.findings),
                    contributions=list(result.verified_contributions),
                    evidence_ids=retained_ids,
                    confidence=min(
                        result.original_analysis.confidence,
                        result.verification.verification_score,
                    ),
                )
            )
            for item in result.verification.verified_evidence:
                evidence = item.evidence
                if evidence.id not in accepted_ids:
                    continue
                if item.status not in (
                    VerificationStatus.VERIFIED,
                    VerificationStatus.PARTIALLY_SUPPORTED,
                ):
                    continue
                if evidence.id in seen_ids:
                    continue
                seen_ids.add(evidence.id)
                candidates.append(
                    ReportEvidenceContext(
                        evidence_id=evidence.id,
                        paper_id=evidence.paper_id,
                        quote=evidence.quote,
                        normalized_fact=evidence.normalized_fact,
                        locator=evidence.locator.model_copy(deep=True),
                        claim=item.claim,
                        confidence=item.entailment_score,
                    )
                )

        selected: list[ReportEvidenceContext] = []
        selected_papers: list[ReportPaperContext] = []
        lines: list[str] = []
        current_size = 0
        # Evidence is budgeted first: structured summaries add useful detail but
        # must never crowd out the exact quotes that ground the final report.
        for candidate in candidates:
            line = self._serialize_record(
                "verified_evidence", candidate.model_dump(mode="json")
            )
            separator_size = 1 if lines else 0
            if current_size + separator_size + len(line) > self.max_context_chars:
                continue
            selected.append(candidate)
            lines.append(line)
            current_size += separator_size + len(line)

        selected_evidence_ids = {item.evidence_id for item in selected}
        for candidate in paper_candidates:
            retained = candidate.model_copy(
                update={
                    "evidence_ids": [
                        key
                        for key in candidate.evidence_ids
                        if key in selected_evidence_ids
                    ]
                },
                deep=True,
            )
            if not retained.evidence_ids:
                continue
            line = self._serialize_record(
                "verified_paper_analysis", retained.model_dump(mode="json")
            )
            separator_size = 1 if lines else 0
            if current_size + separator_size + len(line) > self.max_context_chars:
                continue
            selected_papers.append(retained)
            lines.append(line)
            current_size += separator_size + len(line)

        context_text = "\n".join(lines)
        truncated = (
            len(selected) < len(candidates)
            or len(selected_papers)
            < sum(
                bool(set(item.evidence_ids) & selected_evidence_ids)
                for item in paper_candidates
            )
        )
        if truncated:
            warnings.append(
                "Report evidence context was truncated to the configured "
                "character limit."
            )
        paper_ids = list(dict.fromkeys(item.paper_id for item in selected))
        if len(paper_ids) == 1:
            warnings.append(
                "Evidence coverage is limited to one paper; cross-paper trends "
                "and general conclusions are not established."
            )
        return ReportContext(
            paper_ids=paper_ids,
            papers=deepcopy(selected_papers),
            evidence=deepcopy(selected),
            context_text=context_text,
            char_count=len(context_text),
            max_chars=self.max_context_chars,
            total_available_evidence=len(candidates),
            truncated=truncated,
            warnings=list(dict.fromkeys(warnings)),
        )

    @staticmethod
    def _serialize_record(record_type: str, payload: dict) -> str:
        return json.dumps(
            {"record_type": record_type, **payload},
            ensure_ascii=False,
            separators=(",", ":"),
        )
