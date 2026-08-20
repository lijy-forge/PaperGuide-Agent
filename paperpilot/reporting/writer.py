"""Strict structured LLM writer for evidence-grounded research reports."""

import json

from pydantic import ValidationError

from paperpilot.analysis import StructuredLLMProtocol

from .exceptions import ReportSchemaValidationError, ReportWriterError
from .models import ReportContext, ResearchReport

REPORT_SYSTEM_PROMPT = """You are the senior technical research report writer for
PaperPilot. Produce a rigorous literature review, not a short abstract.

Grounding rules:
- Use only verified_evidence and verified_paper_analysis records in the context.
- Every factual ReportClaim must cite one or more evidence_ids from the context.
- Never invent or alter paper titles, evidence IDs, quotes, paper IDs, metrics,
  source locations, datasets, dates, baselines, or conclusions.
- A search term appearing in the research question is not proof that a paper uses
  that technology. In particular, never infer YOLO usage from phrases such as
  "instance prior", "object detector", or "semantic prior" unless verified
  evidence explicitly identifies YOLO.
- Do not turn a paper author's motivation or claim into an experimentally proven
  result. Preserve uncertainty and distinguish reported facts from synthesis.
- If fewer than two papers are represented, do not claim a research trend or a
  cross-paper consensus. State the coverage limitation prominently.
- Do not add unsupported factual claims merely to make the report look complete.

Report requirements:
- Write in the language of the research question.
- Give a precise title and a substantive executive summary.
- Organize sections to cover: research scope and evidence coverage; paper-by-paper
  methods; technical architecture or integration mechanism; innovations;
  experimental setup and quantitative results; cross-paper comparison (only when
  at least two papers support it); limitations and evidence gaps; and a practical
  implementation roadmap clearly labeled as recommendations rather than reported
  experimental facts.
- Prefer concrete datasets, baselines, metrics, numerical values, modules, inputs,
  outputs, and failure modes when verified context provides them.
- Avoid repetition. Each section should add a distinct analytical dimension.
- Include citations for every used evidence item and copy citation quotes and
  locators exactly. Set paper_title from verified_paper_analysis when available.
- In each section, set evidence_ids to the union of that section's claim
  evidence_ids. Set top-level evidence_ids to the union used by all sections
  and citations.
- Put unavoidable scope and evidence caveats in warnings.

Return only JSON satisfying the requested ResearchReport schema.
"""


class StructuredReportWriter:
    """Generate a ResearchReport through an injected structured LLM protocol."""

    def __init__(self, llm: StructuredLLMProtocol) -> None:
        self.llm = llm

    def write(self, question: str, context: ReportContext) -> ResearchReport:
        """Request and validate one schema-constrained report without repair."""

        normalized_question = question.strip()
        if not normalized_question:
            raise ReportWriterError("report question must not be empty")
        user_prompt = (
            f"Research question:\n{normalized_question}\n\n"
            "The context contains two record types: verified_evidence contains "
            "exact source quotes; verified_paper_analysis contains structured "
            "fields retained after evidence verification. Structured fields may "
            "only be used with their declared evidence_ids.\n\n"
            "Context caveats (summarize relevant items in the report language; "
            "do not copy internal implementation wording verbatim):\n"
            f"{json.dumps(context.warnings, ensure_ascii=False)}\n\n"
            f"Verified report context (JSON Lines):\n{context.context_text}"
        )
        try:
            output = self.llm.generate_structured(
                system_prompt=REPORT_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                response_model=ResearchReport,
            )
        except ValidationError as error:
            raise ReportSchemaValidationError(
                "structured report returned an invalid schema"
            ) from error
        except Exception as error:
            raise ReportWriterError("structured report invocation failed") from error

        if isinstance(output, ResearchReport):
            report = output.model_copy(deep=True)
        else:
            try:
                report = ResearchReport.model_validate(output)
            except ValidationError as error:
                raise ReportSchemaValidationError(
                    "structured report returned an invalid schema"
                ) from error
        if report.question != normalized_question:
            raise ReportSchemaValidationError(
                "structured report question does not match the requested question"
            )
        return self._synchronize_evidence_declarations(report)

    @staticmethod
    def _synchronize_evidence_declarations(report: ResearchReport) -> ResearchReport:
        """Derive redundant declaration fields from validated report references.

        ``section.evidence_ids`` and top-level ``evidence_ids`` are indexes used
        by deterministic verification. They carry no independent prose meaning.
        A structured provider can validly return claim-level evidence while
        omitting these redundant parent indexes, so derive them without adding or
        changing a claim, citation, quote, locator, or evidence identifier.
        Unknown identifiers are intentionally retained and rejected by
        ``ReportVerifier`` at the evidence boundary.
        """

        declared_report_ids = list(report.evidence_ids)
        synchronized_sections = []
        for section in report.sections:
            section_ids = list(section.evidence_ids)
            for claim in section.claims:
                section_ids.extend(claim.evidence_ids)
            normalized_section_ids = list(dict.fromkeys(section_ids))
            declared_report_ids.extend(normalized_section_ids)
            synchronized_sections.append(
                section.model_copy(
                    update={"evidence_ids": normalized_section_ids}, deep=True
                )
            )

        declared_report_ids.extend(
            citation.evidence_id for citation in report.citations
        )
        return report.model_copy(
            update={
                "sections": synchronized_sections,
                "evidence_ids": list(dict.fromkeys(declared_report_ids)),
                "warnings": list(dict.fromkeys(report.warnings)),
            },
            deep=True,
        )
