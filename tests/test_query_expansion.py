"""Offline tests for query expansion and deterministic ordering."""

import unittest

from paperguide.relevance import (
    DeterministicQueryExpansionService,
    QueryVariant,
    ResearchIntent,
    RetrievalBudget,
    RetrievalPlanService,
)
from paperguide.relevance.prompts import (
    INTENT_SYSTEM_PROMPT,
    QUERY_EXPANSION_SYSTEM_PROMPT,
)


class FakePlanner:
    def __init__(self, intent):
        self.intent = intent

    def plan(self, question):
        return self.intent


class FakeExpander:
    def __init__(self, variants):
        self.variants = variants

    def expand(self, intent):
        return list(self.variants)


class QueryExpansionTests(unittest.TestCase):
  def test_multiple_queries_are_deduplicated_and_bounded(self) -> None:
    intent = ResearchIntent(research_question="q", required_concepts=["vision"])
    variants = [
        QueryVariant(query="related topic", purpose="related concept query"),
        QueryVariant(query="Vision", purpose="direct required concept query"),
        QueryVariant(query=" vision ", purpose="duplicate"),
    ]
    plan = RetrievalPlanService(FakePlanner(intent), FakeExpander(variants)).build(
        "q", max_core_papers=3, budget=RetrievalBudget(max_core_papers=3, max_query_variants=2)
    )
    self.assertEqual([item.query for item in plan.query_variants], ["Vision", "related topic"])


  def test_expansion_fallback_is_safe(self) -> None:
    intent = ResearchIntent(research_question="q", required_concepts=["vision"])
    plan = RetrievalPlanService(FakePlanner(intent), FakeExpander([])).build("q", max_core_papers=2)
    self.assertEqual(plan.query_variants[0].purpose, "fallback")
    self.assertIn("QUERY_EXPANSION_FALLBACK", plan.warnings)


  def test_deterministic_demo_expander_does_not_need_llm(self) -> None:
    intent = ResearchIntent(
        research_question="研究问题", required_concepts=["visual SLAM"], relation_requirements=["fusion"]
    )
    result = DeterministicQueryExpansionService().expand(intent)
    self.assertEqual(result[0].query, "visual SLAM")
    self.assertEqual(result[0].covered_relations, ["fusion"])


  def test_production_prompts_require_english_scholarly_terms(self) -> None:
    self.assertIn("canonical English academic terminology", INTENT_SYSTEM_PROMPT)
    self.assertIn("concise English academic", QUERY_EXPANSION_SYSTEM_PROMPT)
    self.assertIn("Use only concepts and", QUERY_EXPANSION_SYSTEM_PROMPT)
