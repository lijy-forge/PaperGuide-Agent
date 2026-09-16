"""Deterministic evidence and citation checks for structured reports."""

import re
from copy import deepcopy

from .exceptions import ReportVerificationError
from .models import ReportContext, ResearchReport


class ReportVerifier:
    """Reject invalid references and annotate explicitly unsupported claims."""

    def verify(
        self,
        report: ResearchReport,
        context: ReportContext,
    ) -> ResearchReport:
        """Return an isolated verified report or raise on invalid grounding."""

        evidence_by_id = {item.evidence_id: item for item in context.evidence}
        paper_titles = {item.paper_id: item.title for item in context.papers}
        report_evidence_ids = set(report.evidence_ids)
        errors: list[str] = []
        warnings = list(report.warnings)

        for evidence_id in report.evidence_ids:
            if evidence_id not in evidence_by_id:
                errors.append(f"report references unknown evidence {evidence_id}")

        for section in report.sections:
            section_ids = set(section.evidence_ids)
            for evidence_id in section.evidence_ids:
                if evidence_id not in evidence_by_id:
                    errors.append(
                        f"section {section.title!r} references unknown evidence "
                        f"{evidence_id}"
                    )
                elif evidence_id not in report_evidence_ids:
                    errors.append(
                        f"section {section.title!r} evidence is not declared "
                        "by the report"
                    )
            for claim in section.claims:
                if not claim.evidence_ids:
                    warnings.append(
                        f"Unsupported claim in section {section.title!r}: {claim.text}"
                    )
                    continue
                for evidence_id in claim.evidence_ids:
                    if evidence_id not in evidence_by_id:
                        errors.append(
                            f"claim {claim.text!r} references unknown evidence "
                            f"{evidence_id}"
                        )
                    elif evidence_id not in section_ids:
                        errors.append(
                            f"claim {claim.text!r} evidence is not declared "
                            "by its section"
                        )

        for citation in report.citations:
            evidence = evidence_by_id.get(citation.evidence_id)
            if evidence is None:
                errors.append(
                    f"citation references unknown evidence {citation.evidence_id}"
                )
                continue
            if citation.evidence_id not in report_evidence_ids:
                errors.append("citation evidence is not declared by the report")
            if citation.paper_id != evidence.paper_id:
                errors.append("citation paper_id does not match verified evidence")
            if citation.quote != evidence.quote:
                errors.append("citation quote does not match verified evidence")
            if citation.locator != evidence.locator:
                errors.append("citation locator does not match verified evidence")
            expected_title = paper_titles.get(citation.paper_id)
            if (
                citation.paper_title is not None
                and expected_title is not None
                and citation.paper_title != expected_title
            ):
                errors.append("citation paper_title does not match verified analysis")

        cited_ids = {item.evidence_id for item in report.citations}
        claim_ids = {
            evidence_id
            for section in report.sections
            for claim in section.claims
            for evidence_id in claim.evidence_ids
        }
        for evidence_id in claim_ids - cited_ids:
            errors.append(f"claim evidence {evidence_id} has no citation")

        if errors:
            raise ReportVerificationError("; ".join(dict.fromkeys(errors)))
        self._validate_public_prose(report)
        verified = report.model_copy(deep=True)
        verified.citations = [
            citation.model_copy(
                update={
                    "paper_title": citation.paper_title
                    or paper_titles.get(citation.paper_id)
                },
                deep=True,
            )
            for citation in verified.citations
        ]
        verified.warnings = list(dict.fromkeys(warnings))
        if len(context.paper_ids) == 1:
            coverage_warning = (
                "当前已验证证据仅覆盖 1 篇论文，不足以形成跨论文趋势或共识结论。"
                if re.search(r"[\u3400-\u9fff]", verified.question)
                else "Verified evidence covers one paper only; cross-paper trends "
                "or consensus conclusions are not established."
            )
            verified.warnings = list(
                dict.fromkeys([*verified.warnings, coverage_warning])
            )
        return deepcopy(verified)

    @staticmethod
    def _validate_public_prose(report: ResearchReport) -> None:
        """Reject provider prose that attempts to publish internal linkage IDs."""

        pattern = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.I)
        internal = re.compile(r"\b(?:paper_id|statement_key|evidence_id|evidence_key|task_id|execution_id)\b", re.I)
        values = [report.question, report.title, report.summary, *report.warnings]
        values.extend(section.title for section in report.sections)
        values.extend(claim.text for section in report.sections for claim in section.claims)
        if any(pattern.search(value) or internal.search(value) for value in values):
            raise ReportVerificationError("PUBLIC_INTERNAL_ID_LEAK")
