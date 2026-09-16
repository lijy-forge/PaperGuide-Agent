"""Deterministic internal-consistency checks before report export."""

from paperguide.reporting import ResearchReport

from .exceptions import ExportValidationError


class ExportVerifier:
    """Reject incomplete citations, unknown evidence, and unsupported claims."""

    def verify(self, report: ResearchReport) -> ResearchReport:
        """Return an isolated exportable report or raise a validation error."""

        declared_ids = set(report.evidence_ids)
        errors: list[str] = []
        if len(declared_ids) != len(report.evidence_ids):
            errors.append("report evidence_ids contain duplicates")

        citation_ids = set()
        citation_signatures: dict = {}
        for citation in report.citations:
            if not citation.quote.strip():
                errors.append(
                    f"citation for evidence {citation.evidence_id} has an empty quote"
                )
            if citation.locator.paper_id != citation.paper_id:
                errors.append(
                    f"citation for evidence {citation.evidence_id} has an "
                    "invalid locator"
                )
            if citation.evidence_id not in declared_ids:
                errors.append(
                    f"citation references undeclared evidence {citation.evidence_id}"
                )
            signature = (citation.paper_id, citation.quote, citation.locator)
            previous = citation_signatures.get(citation.evidence_id)
            if previous is not None and previous != signature:
                errors.append(
                    f"evidence {citation.evidence_id} has conflicting citations"
                )
            citation_signatures[citation.evidence_id] = signature
            citation_ids.add(citation.evidence_id)

        for evidence_id in declared_ids - citation_ids:
            errors.append(f"evidence {evidence_id} has no complete citation")

        for section in report.sections:
            section_ids = set(section.evidence_ids)
            for evidence_id in section_ids:
                if evidence_id not in declared_ids:
                    errors.append(
                        f"section {section.title!r} references undeclared evidence "
                        f"{evidence_id}"
                    )
            for claim in section.claims:
                if not claim.evidence_ids:
                    errors.append(
                        f"unsupported claim blocks export: {claim.text}"
                    )
                    continue
                for evidence_id in claim.evidence_ids:
                    if evidence_id not in declared_ids:
                        errors.append(
                            f"claim {claim.text!r} references undeclared evidence "
                            f"{evidence_id}"
                        )
                    elif evidence_id not in section_ids:
                        errors.append(
                            f"claim {claim.text!r} evidence is not declared "
                            "by section"
                        )

        has_unsupported_warning = any(
            "unsupported claim" in warning.casefold() for warning in report.warnings
        )
        if has_unsupported_warning:
            errors.append("report contains an unsupported-claim warning")
        if errors:
            raise ExportValidationError("; ".join(dict.fromkeys(errors)))
        return report.model_copy(deep=True)
