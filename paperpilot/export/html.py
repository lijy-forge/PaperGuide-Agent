"""Escaped standalone HTML rendering with public academic citations only."""

from html import escape
from pathlib import Path

from paperpilot.reporting import ResearchReport, build_public_report_citation_index

from .markdown import _format_locator, _write_text
from .models import ExportFormat, ExportResult
from .verifier import ExportVerifier


class HTMLExporter:
    """Render an evidence-grounded report without UUID anchors or labels."""

    def __init__(self, verifier: ExportVerifier | None = None) -> None:
        self.verifier = verifier or ExportVerifier()

    def render(self, report: ResearchReport) -> str:
        safe_report = self.verifier.verify(report)
        index = build_public_report_citation_index(safe_report.citations)
        sections = []
        for section in safe_report.sections:
            claims = []
            for claim in section.claims:
                refs = " ".join(
                    f'<a href="#reference-{number}">{escape(token)}</a>'
                    for token, number in _linked_tokens(index, claim.evidence_ids)
                )
                claims.append(f"<li>{escape(claim.text)} {refs}</li>")
            sections.append(f"<section><h2>{escape(section.title)}</h2><ul>{''.join(claims)}</ul></section>")
        references = "".join(
            f'<li id="reference-{number}">[{number}] {escape(title or "Verified source paper")}</li>'
            for number, title in sorted(index.titles_by_number.items())
        )
        ledger = "".join(
            f"<tr><td>[{index.numbers_by_evidence[item.evidence_id]}]</td>"
            f"<td>{escape(item.paper_title or 'Verified source paper')}</td>"
            f"<td>{escape(_format_locator(item.locator))}</td>"
            f"<td>{escape(item.quote)}</td></tr>"
            for item in safe_report.citations
        )
        warnings = "".join(f"<li>{escape(value)}</li>" for value in safe_report.warnings)
        warning_section = f'<aside class="warnings"><h2>Warnings</h2><ul>{warnings}</ul></aside>' if warnings else ""
        return (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f"<title>{escape(safe_report.title)}</title>"
            "<style>body{font-family:system-ui,sans-serif;max-width:960px;margin:2rem auto;line-height:1.5}.evidence-card{border:1px solid #ccc;padding:1rem;margin:1rem 0}.warnings{border-left:4px solid #b45309;padding:1rem}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:.5rem;text-align:left}a{color:#155e75}</style></head><body>"
            f"<h1>{escape(safe_report.title)}</h1><p><strong>Research question:</strong> {escape(safe_report.question)}</p><p>{escape(safe_report.summary)}</p>"
            f"{''.join(sections)}<section><h2>References</h2><ol>{references}</ol></section>"
            f'<section><h2>Evidence Ledger</h2><table><thead><tr><th>Citation</th><th>Paper</th><th>Location</th><th>Quote</th></tr></thead><tbody>{ledger}</tbody></table></section>{warning_section}</body></html>'
        )

    def export(self, report: ResearchReport, output_path: str | Path | None = None) -> ExportResult:
        content = self.render(report)
        file_path = _write_text(content, output_path) if output_path is not None else None
        return ExportResult(format=ExportFormat.HTML, media_type="text/html; charset=utf-8", content=content, file_path=file_path, size_bytes=len(content.encode("utf-8")), warnings=list(report.warnings))


def _linked_tokens(index, evidence_ids):
    """Return public tokens linked only to numeric reference anchors."""

    refs = index.refs_for_evidence_ids(evidence_ids)
    if not refs:
        return []
    token = refs[0]
    numbers = sorted({index.numbers_by_evidence[item] for item in evidence_ids if item in index.numbers_by_evidence})
    return [(token, numbers[0])] if numbers else []
