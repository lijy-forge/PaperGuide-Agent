"""Budget and planner fallback tests."""

import unittest

from paperguide.relevance import (
    QueryVariant,
    ResearchIntent,
    RetrievalBudget,
    RetrievalPlanService,
)


class FailingPlanner:
    def plan(self, question):
        raise RuntimeError("secret provider detail")


class FailingExpander:
    def expand(self, intent):
        raise RuntimeError("secret expansion detail")


class RetrievalPlanTests(unittest.TestCase):
  def test_planner_and_expander_failures_fallback_without_details(self) -> None:
    plan = RetrievalPlanService(FailingPlanner(), FailingExpander()).build(
        "original question", max_core_papers=4
    )
    self.assertEqual(plan.intent.required_concepts, ["original question"])
    self.assertEqual(plan.query_variants[0].query, "original question")
    self.assertIn("INTENT_PLANNER_FALLBACK", plan.warnings)
    self.assertIn("QUERY_EXPANSION_FALLBACK", plan.warnings)
    self.assertNotIn("secret", " ".join(plan.warnings))


  def test_budget_maps_max_papers_to_core_budget_and_exposes_metrics(self) -> None:
    intent = ResearchIntent(research_question="q", required_concepts=["q"])
    plan = RetrievalPlanService(
        type("P", (), {"plan": lambda self, question: intent})(),
        type("E", (), {"expand": lambda self, value: [QueryVariant(query="q", purpose="direct")]})(),
    ).build("q", max_core_papers=7, budget=RetrievalBudget(max_core_papers=1))
    self.assertEqual(plan.budget.max_core_papers, 7)
    self.assertEqual(plan.planned_query_count, 1)
    self.assertEqual(plan.max_candidate_budget, 50)
    self.assertEqual(plan.max_document_budget, 12)
    self.assertEqual(plan.max_reader_budget, 10)


  def test_request_language_is_deterministically_persisted_on_intent(self) -> None:
    intent = ResearchIntent(research_question="ignored", required_concepts=["ignored"], query_language="en")
    plan = RetrievalPlanService(
        type("P", (), {"plan": lambda self, question: intent})(),
        type("E", (), {"expand": lambda self, value: [QueryVariant(query="q", purpose="direct")]})(),
    ).build("目标检测与视觉 SLAM 融合", max_core_papers=3)
    self.assertEqual(plan.intent.query_language, "zh")


  def test_output_form_terms_do_not_become_per_paper_relevance_gates(self) -> None:
    intent = ResearchIntent(
        research_question="SLAM文献综述",
        required_concepts=["SLAM", "survey", "review"],
        relation_requirements=["surveys of SLAM published between 2000 and 2026"],
    )
    plan = RetrievalPlanService(
        type("P", (), {"plan": lambda self, question: intent})(),
        type("E", (), {"expand": lambda self, value: [QueryVariant(query="SLAM", purpose="direct")]})(),
    ).build("SLAM文献综述", max_core_papers=15)

    self.assertEqual(plan.intent.required_concepts, ["SLAM"])
    self.assertEqual(plan.intent.relation_requirements, [])
    self.assertIn("INTENT_OUTPUT_FORM_TERMS_REMOVED", plan.warnings)


  def test_invalid_budget_is_rejected(self) -> None:
    with self.assertRaises(ValueError):
        RetrievalBudget(max_core_papers=0)
