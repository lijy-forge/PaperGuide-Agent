"""Objective checks over one generated survey.

Two kinds live here.

*Invariants* are properties the pipeline promises unconditionally: a citation
that resolves, a quote that really occurs in the source, no internal
identifier in reader-facing text. A violation is a defect, so they return
pass/fail.

*Metrics* are ratios that only mean something next to a baseline — evidence
coverage, rejection rate. They return numbers, and the runner compares them
against the thresholds a case declares.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.I,
)
CITATION_PATTERN = re.compile(r"\[(\d+)(?:\s*,\s*(?:\d+|p\.\s*\d+))*\]")
INTERNAL_KEYS = ("statement_key", "evidence_key", "paper_id", "execution_id")


@dataclass(frozen=True)
class CheckResult:
    """One invariant verdict, with the first offending value when it fails."""

    name: str
    passed: bool
    detail: str = ""


def _prose(report) -> str:
    """Concatenate every reader-facing string in the report."""

    parts = [report.title, report.abstract]
    for section in report.sections:
        parts.append(section.title)
        parts.extend(paragraph.text for paragraph in section.paragraphs)
        parts.extend(claim.text for claim in section.claims)
    return "\n".join(str(part) for part in parts if part)


def citations_resolve(report) -> CheckResult:
    """Every bracketed number in prose must name a registered reference."""

    registered = {item.citation_number for item in report.references}
    for match in CITATION_PATTERN.finditer(_prose(report)):
        number = int(match.group(1))
        if number not in registered:
            return CheckResult(
                "citations_resolve",
                False,
                f"[{number}] is not in the reference list",
            )
    return CheckResult("citations_resolve", True)


def evidence_is_locatable(report) -> CheckResult:
    """Every ledger entry must carry a locator and a non-empty quote."""

    for entry in report.evidence_appendix:
        if not getattr(entry, "quote", None):
            return CheckResult(
                "evidence_is_locatable",
                False,
                f"[{entry.citation_number}] has no quote",
            )
        if entry.page is None and not getattr(entry, "section_title", None):
            return CheckResult(
                "evidence_is_locatable",
                False,
                f"[{entry.citation_number}] has neither page nor section",
            )
    return CheckResult("evidence_is_locatable", True)


def no_internal_identifiers(report) -> CheckResult:
    """Reader-facing output must not leak private linkage tokens."""

    payload = str(report.public_dict())
    match = UUID_PATTERN.search(payload)
    if match:
        return CheckResult(
            "no_internal_identifiers",
            False,
            f"uuid leaked: {match.group(0)[:8]}…",
        )
    for key in INTERNAL_KEYS:
        if key in payload:
            return CheckResult("no_internal_identifiers", False, f"{key} leaked")
    return CheckResult("no_internal_identifiers", True)


def references_have_provenance(report) -> CheckResult:
    """Every reference needs at least one stable identifier to be checkable."""

    for reference in report.references:
        stable = any(
            (
                reference.doi,
                reference.arxiv_id,
                reference.semantic_scholar_id,
                reference.openalex_id,
                reference.source_url,
            )
        )
        if not stable:
            return CheckResult(
                "references_have_provenance",
                False,
                f"[{reference.citation_number}] has no resolvable identifier",
            )
    return CheckResult("references_have_provenance", True)


INVARIANTS = {
    "citations_resolve": citations_resolve,
    "evidence_is_locatable": evidence_is_locatable,
    "no_internal_identifiers": no_internal_identifiers,
    "references_have_provenance": references_have_provenance,
}


def evidence_coverage(report) -> float:
    """Share of ledger entries whose statement is fully supported."""

    entries = report.evidence_appendix
    if not entries:
        return 0.0
    supported = sum(
        1 for item in entries if str(item.support_status.value) == "supported"
    )
    return supported / len(entries)


def citation_density(report) -> float:
    """Average distinct references cited per paragraph.

    A report where every paragraph cites the whole sample scores the same as
    the reference count, which is the signature of citation padding rather
    than evidence binding.
    """

    paragraphs = [
        paragraph
        for section in report.sections
        for paragraph in section.paragraphs
        if paragraph.citation_refs
    ]
    if not paragraphs:
        return 0.0
    # A ref is one bracketed group such as "[1,2,3]" or "[4, p.7]", so the
    # distinct references it names have to be parsed out of the string.
    total = 0
    for paragraph in paragraphs:
        numbers: set[int] = set()
        for ref in paragraph.citation_refs:
            # Drop page locators first so "p.7" is not counted as reference 7.
            without_pages = re.sub(r"p\.\s*\d+", "", ref)
            numbers.update(int(value) for value in re.findall(r"\d+", without_pages))
        total += len(numbers)
    return total / len(paragraphs)


METRICS = {
    "evidence_coverage": evidence_coverage,
    "citation_density": citation_density,
}
