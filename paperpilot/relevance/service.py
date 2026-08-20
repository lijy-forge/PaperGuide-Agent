"""Deterministic orchestration of intent, query, and retrieval budgets."""

import re
from time import monotonic

from .audit import classify_text_language
from .diagnostics import (
    PlanningDiagnosticCallback,
    PlanningStageDiagnostic,
    classify_planning_failure,
)
from .models import QueryVariant, ResearchIntent, RetrievalBudget, RetrievalPlan
from .language import language_from_question
from .protocols import QueryExpansionProtocol, ResearchIntentPlannerProtocol


class RetrievalPlanService:
    """Build a bounded plan and isolate planner/expander failures."""

    def __init__(self, planner: ResearchIntentPlannerProtocol, expander: QueryExpansionProtocol):
        self._planner = planner
        self._expander = expander

    def build(
        self,
        question: str,
        *,
        max_core_papers: int,
        budget: RetrievalBudget | None = None,
        diagnostic_callback: PlanningDiagnosticCallback | None = None,
    ) -> RetrievalPlan:
        normalized = question.strip()
        if not normalized:
            raise ValueError("research question must not be empty")
        if not 1 <= max_core_papers <= 50:
            raise ValueError("max_core_papers must be between 1 and 50")
        effective_budget = (budget or RetrievalBudget(max_core_papers=max_core_papers)).model_copy(update={"max_core_papers": max_core_papers})
        warnings: list[str] = []
        planner_started = monotonic()
        self._emit(
            diagnostic_callback,
            PlanningStageDiagnostic(stage="intent_planner", outcome="started"),
        )
        try:
            intent = self._planner.plan(normalized)
            if not isinstance(intent, ResearchIntent):
                intent = ResearchIntent.model_validate(intent)
        except Exception as error:
            intent = ResearchIntent(research_question=normalized, required_concepts=[normalized])
            warnings.append("INTENT_PLANNER_FALLBACK")
            category, class_name, parsed, validated = classify_planning_failure(
                error, stage="intent_planner"
            )
            self._emit(
                diagnostic_callback,
                PlanningStageDiagnostic(
                    stage="intent_planner",
                    outcome="fallback",
                    failure_category=category,
                    exception_class_safe=class_name,
                    elapsed_ms=(monotonic() - planner_started) * 1000,
                    fallback_reason_code="INTENT_PLANNER_EXCEPTION",
                    json_parse_reached=parsed,
                    schema_validation_reached=validated,
                    **self._intent_counts(intent),
                ),
            )
        else:
            self._emit(
                diagnostic_callback,
                PlanningStageDiagnostic(
                    stage="intent_planner",
                    outcome="succeeded",
                    elapsed_ms=(monotonic() - planner_started) * 1000,
                    json_parse_reached=True,
                    schema_validation_reached=True,
                    output_count=1,
                    **self._intent_counts(intent),
                ),
            )
        # User-visible language is derived once from the original request, not
        # from an optional LLM field or later rendered prose.
        intent = intent.model_copy(
            update={"query_language": language_from_question(normalized)}
        )
        expansion_started = monotonic()
        self._emit(
            diagnostic_callback,
            PlanningStageDiagnostic(stage="query_expansion", outcome="started"),
        )
        try:
            variants = self._expander.expand(intent)
            variants = [
                item if isinstance(item, QueryVariant) else QueryVariant.model_validate(item)
                for item in variants
            ]
            if not variants:
                raise ValueError("query expansion returned no variants")
        except Exception as error:
            variants = [
                QueryVariant(
                    query=normalized,
                    purpose="fallback",
                    covered_concepts=list(intent.required_concepts),
                    covered_relations=list(intent.relation_requirements),
                )
            ]
            warnings.append("QUERY_EXPANSION_FALLBACK")
            category, class_name, parsed, validated = classify_planning_failure(
                error, stage="query_expansion"
            )
            self._emit(
                diagnostic_callback,
                PlanningStageDiagnostic(
                    stage="query_expansion",
                    outcome="fallback",
                    failure_category=category,
                    exception_class_safe=class_name,
                    elapsed_ms=(monotonic() - expansion_started) * 1000,
                    fallback_query_count=1,
                    fallback_reason_code="QUERY_EXPANSION_EXCEPTION",
                    json_parse_reached=parsed,
                    schema_validation_reached=validated,
                    output_count=1,
                ),
            )
        else:
            self._emit(
                diagnostic_callback,
                PlanningStageDiagnostic(
                    stage="query_expansion",
                    outcome="succeeded",
                    elapsed_ms=(monotonic() - expansion_started) * 1000,
                    json_parse_reached=True,
                    schema_validation_reached=True,
                    output_count=len(variants),
                ),
            )
        variants = self._normalize_and_bound(variants, effective_budget.max_query_variants)
        if not variants:
            variants = [
                QueryVariant(
                    query=normalized,
                    purpose="fallback",
                    covered_concepts=list(intent.required_concepts),
                    covered_relations=list(intent.relation_requirements),
                )
            ]
            warnings.append("QUERY_EXPANSION_FALLBACK")
            self._emit(
                diagnostic_callback,
                PlanningStageDiagnostic(
                    stage="query_expansion",
                    outcome="fallback",
                    failure_category="INVALID_EXPANSION_OUTPUT",
                    exception_class_safe="None",
                    elapsed_ms=(monotonic() - expansion_started) * 1000,
                    fallback_query_count=1,
                    fallback_reason_code="EMPTY_NORMALIZED_VARIANTS",
                    json_parse_reached=True,
                    schema_validation_reached=True,
                    output_count=1,
                ),
            )
        return RetrievalPlan(
            intent=intent,
            query_variants=variants,
            budget=effective_budget,
            warnings=list(dict.fromkeys(warnings)),
        )

    @staticmethod
    def _emit(
        callback: PlanningDiagnosticCallback | None,
        diagnostic: PlanningStageDiagnostic,
    ) -> None:
        if callback is None:
            return
        try:
            callback(diagnostic)
        except Exception:
            return

    @staticmethod
    def _intent_counts(intent: ResearchIntent) -> dict[str, object]:
        language_counts = {"ZH": 0, "EN": 0, "MIXED": 0}
        for term in [
            *intent.required_concepts,
            *intent.related_concepts,
            *intent.relation_requirements,
            *intent.exclusion_concepts,
        ]:
            language = classify_text_language(term)
            if language in language_counts:
                language_counts[language] += 1
        return {
            "required_concept_count": len(intent.required_concepts),
            "related_concept_count": len(intent.related_concepts),
            "relation_requirement_count": len(intent.relation_requirements),
            "exclusion_concept_count": len(intent.exclusion_concepts),
            "domain_present": bool(intent.domain),
            "time_range_present": intent.time_range is not None,
            "query_language_present": bool(intent.query_language),
            "zh_term_count": language_counts["ZH"],
            "en_term_count": language_counts["EN"],
            "mixed_term_count": language_counts["MIXED"],
        }

    @staticmethod
    def _normalize_and_bound(
        variants: list[QueryVariant], limit: int
    ) -> list[QueryVariant]:
        unique: dict[str, QueryVariant] = {}
        for variant in variants:
            query = " ".join(variant.query.split())
            if not query:
                continue
            key = re.sub(r"\s+", " ", query).casefold()
            if key not in unique:
                unique[key] = variant.model_copy(update={"query": query})
        def priority(item: QueryVariant) -> tuple[int, str]:
            purpose = item.purpose.casefold()
            rank = (
                0
                if "direct" in purpose
                else 1
                if "relation" in purpose or item.covered_relations
                else 2
                if "related" in purpose
                else 3
            )
            return rank, item.query.casefold()

        return sorted(unique.values(), key=priority)[:limit]
