"""Safe public-Markdown rendering for evidence-grounded research reports."""

from html import escape
from pathlib import Path

from paperpilot.domain import SourceLocator
from paperpilot.reporting import ResearchReport, build_public_report_citation_index

from .exceptions import ExportWriteError
from .models import ExportFormat, ExportResult
from .verifier import ExportVerifier


class MarkdownExporter:
    """Render verified reports without exposing internal evidence identifiers."""

    def __init__(self, verifier: ExportVerifier | None = None) -> None:
        self.verifier = verifier or ExportVerifier()

    def render(self, report: ResearchReport) -> str:
        """Return citation-safe Markdown without changing the input report."""

        safe_report = self.verifier.verify(report)
        index = build_public_report_citation_index(safe_report.citations)
        lines = [
            f"# {escape(safe_report.title)}", "",
            f"**Research question:** {escape(safe_report.question)}", "",
            escape(safe_report.summary),
        ]
        for section in safe_report.sections:
            lines.extend(["", f"## {escape(section.title)}", ""])
            for claim in section.claims:
                refs = " ".join(index.refs_for_evidence_ids(claim.evidence_ids))
                lines.append(f"- {escape(claim.text)} {refs}".rstrip())

        lines.extend(["", "## References", ""])
        for number, title in sorted(index.titles_by_number.items()):
            lines.append(f"[{number}] {escape(title or 'Verified source paper')}")

        lines.extend(["", "## Evidence Ledger", ""])
        for citation in safe_report.citations:
            number = index.numbers_by_evidence[citation.evidence_id]
            title = citation.paper_title or index.titles_by_number[number] or "Verified source paper"
            lines.append(
                f"[{number}] {escape(title)} — “{escape(citation.quote)}” "
                f"({_format_locator(citation.locator)})"
            )
        if safe_report.warnings:
            lines.extend(["", "## Scope and evidence limitations", ""])
            lines.extend(f"- {escape(warning)}" for warning in safe_report.warnings)
        return "\n".join(lines).rstrip() + "\n"

    def export(self, report: ResearchReport, output_path: str | Path | None = None) -> ExportResult:
        content = self.render(report)
        file_path = _write_text(content, output_path) if output_path is not None else None
        return ExportResult(format=ExportFormat.MARKDOWN, media_type="text/markdown; charset=utf-8", content=content, file_path=file_path, size_bytes=len(content.encode("utf-8")), warnings=list(report.warnings))


def _format_locator(locator: SourceLocator) -> str:
    values: list[str] = []
    if locator.section_title:
        values.append(f"section {escape(locator.section_title)}")
    if locator.page_start is not None:
        page = str(locator.page_start)
        if locator.page_end is not None and locator.page_end != locator.page_start:
            page = f"{page}-{locator.page_end}"
        values.append(f"p.{page}")
    if locator.paragraph_index is not None:
        values.append(f"paragraph {locator.paragraph_index}")
    return "; ".join(values) or "source location retained"


def _write_text(content: str, output_path: str | Path) -> str:
    path = Path(output_path)
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as error:
        raise ExportWriteError(f"could not write export file {path}") from error
    return str(path.resolve())
