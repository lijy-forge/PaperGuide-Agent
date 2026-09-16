"""Versioned provider-neutral prompts for structured paper reading."""

from paperguide.analysis.models import PaperContext

PAPER_READER_PROMPT_VERSION = "v3"

PAPER_READER_SYSTEM_PROMPT = """You are a rigorous technical paper reader.
Use only the supplied paper context. Do not fill gaps from the title, common
knowledge, or assumptions. Every important method or experimental claim must
reference an evidence_key. Each contribution and limitation must have a corresponding evidence entry whose claim is semantically entailed by its quote. Each evidence quote must be a short verbatim excerpt
from the context, and its page_number and section_title must match the location
markers. Distinguish author statements and experimental facts from your own
inferences; do not present an inference as direct evidence. Never invent datasets,
metrics, values, baselines, citations, or implementation details. Preserve metric
units and comparison directions. When information is absent, use an empty list,
null where allowed, or analysis_warnings. Return only JSON satisfying the requested
PaperReaderOutput schema. Write analytical prose in Simplified Chinese. Preserve
paper titles, method names, dataset names, metric names, abbreviations, and every
verbatim evidence quote in its original language."""


def build_paper_reader_user_prompt(context: PaperContext) -> str:
    """Build the paper-specific task prompt from a controlled context."""

    return f"""Analyze this paper as a single, self-contained source.

Paper title: {context.title}

Required output:
- identify the research problem and only author-explicit contributions;
- summarize the method, architecture, innovations, and author-stated limitations;
- inspect Contribution, Discussion, Limitations, Threats to Validity, Conclusion,
  and Future Work sections before deciding that contribution or limitation evidence
  is absent;
- do not relabel a generic result, background sentence, or title inference as a
  contribution or limitation; return an empty list when the author does not state it;
- extract experiments, datasets, baselines, metrics, values, and findings;
- provide short evidence entries with unique evidence_key values; every evidence
  claim must be directly and semantically supported by its exact quote;
- make method.evidence_keys and experiments.evidence_keys reference those entries;
- include dedicated evidence for the strongest contribution and limitation when
  available; return at most 10 evidence entries and keep every verbatim quote under
  500 characters;
- return at most 5 contributions, 8 architecture items, 5 innovations,
  5 limitations, 12 metrics, and 8 experimental findings;
- keep summaries concise and do not repeat the same fact across fields;
- record missing or uncertain information in analysis_warnings;
- output all fields required by the supplied JSON schema and no extra fields.

Controlled paper context:
{context.context_text}
"""
