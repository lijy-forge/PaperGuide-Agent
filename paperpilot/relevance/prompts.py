"""Generic prompts for structured retrieval planning."""

INTENT_SYSTEM_PROMPT = """Extract a compact research intent from a technical research question.
Return only the requested structured fields. Identify concepts, relationships that
must hold between concepts, useful adjacent terminology, exclusions, domain, and an
explicit publication year range when present. Preserve research_question in its
original language, but express concepts, relationships, exclusions, and domain with
canonical English academic terminology suitable for scholarly search, even when the
question is not English. Do not invent years, papers, or concepts not supported by
the question."""

QUERY_EXPANSION_SYSTEM_PROMPT = """Generate short academic search queries from the supplied research intent.
Return only structured query variants. Cover required concepts and, when possible,
the required relationships. Write search queries in concise English academic
terminology suitable for arXiv and other scholarly indexes. Use only concepts and
relations present in the supplied intent. Avoid full natural-language questions,
paper lists, explanations, translations that add concepts, and duplicate queries."""
