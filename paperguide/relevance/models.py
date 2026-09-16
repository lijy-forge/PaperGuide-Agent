"""Structured contracts for research intent and bounded retrieval planning."""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TimeRange(BaseModel):
    """An explicit publication-year range supplied by the research question."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_year: int | None = Field(default=None, ge=1)
    end_year: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_order(self) -> "TimeRange":
        if self.start_year is not None and self.end_year is not None and self.start_year > self.end_year:
            raise ValueError("start_year must be less than or equal to end_year")
        return self


class ResearchIntent(BaseModel):
    """LLM- or rule-derived interpretation of a technical research question."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    research_question: str
    required_concepts: list[str] = Field(
        min_length=1,
        max_length=6,
        description="Canonical English academic concepts required by the question.",
    )
    related_concepts: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Canonical English adjacent terms useful for scholarly retrieval.",
    )
    relation_requirements: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="Required relationships expressed in concise academic English.",
    )
    exclusion_concepts: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="English terms describing concepts explicitly outside the scope.",
    )
    domain: str | None = Field(
        default=None,
        description="Canonical English name of the technical or scientific domain.",
    )
    time_range: TimeRange | None = None
    query_language: str | None = None

    @field_validator("research_question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("research_question must not be empty")
        return value

    @field_validator("required_concepts", "related_concepts", "relation_requirements", "exclusion_concepts")
    @classmethod
    def normalize_terms(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = " ".join(value.split())
            key = item.casefold()
            if item and key not in seen:
                normalized.append(item)
                seen.add(key)
        return normalized


class QueryVariant(BaseModel):
    """One short academic-search expression and the intent it covers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(
        description="A concise English academic search expression using only the intent terms."
    )
    purpose: str = Field(description="The distinct retrieval purpose of this query.")
    covered_concepts: list[str] = Field(default_factory=list)
    covered_relations: list[str] = Field(default_factory=list)

    @field_validator("query", "purpose")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("query and purpose must not be empty")
        return value


class QueryExpansionOutput(BaseModel):
    """Strict structured response accepted from a query-expansion LLM."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    variants: list[QueryVariant] = Field(min_length=1, max_length=50)


class RetrievalBudget(BaseModel):
    """Deterministic cost limits applied before retrieval and downstream work."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_query_variants: int = Field(default=5, ge=1, le=20)
    max_candidates_per_query: int = Field(default=10, ge=1, le=100)
    max_candidates_after_dedup: int = Field(default=30, ge=1, le=200)
    max_documents_to_ingest: int = Field(default=12, ge=1, le=50)
    max_papers_to_read: int = Field(default=10, ge=1, le=50)
    max_core_papers: int = Field(ge=1, le=50)


class RetrievalPlan(BaseModel):
    """Auditable, bounded plan produced before any retriever is called."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: ResearchIntent
    query_variants: list[QueryVariant] = Field(min_length=1)
    budget: RetrievalBudget
    warnings: list[str] = Field(default_factory=list)

    @property
    def planned_query_count(self) -> int:
        return len(self.query_variants)

    @property
    def max_candidate_budget(self) -> int:
        return self.budget.max_query_variants * self.budget.max_candidates_per_query

    @property
    def max_document_budget(self) -> int:
        return self.budget.max_documents_to_ingest

    @property
    def max_reader_budget(self) -> int:
        return self.budget.max_papers_to_read

    @property
    def max_core_budget(self) -> int:
        return self.budget.max_core_papers
