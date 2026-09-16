"""Offline tests for the structured research-intent contract."""

import unittest

from paperguide.relevance import ResearchIntent, StructuredLLMResearchIntentPlanner, TimeRange


class ResearchIntentTests(unittest.TestCase):
  def test_schema_describes_retrieval_terms_as_english(self) -> None:
    schema = ResearchIntent.model_json_schema()
    self.assertIn("Canonical English", schema["properties"]["required_concepts"]["description"])
    self.assertIn("academic English", schema["properties"]["relation_requirements"]["description"])

  def test_intent_supports_concepts_relations_and_time_range(self) -> None:
    intent = ResearchIntent(
        research_question="Analyze multimodal fusion",
        required_concepts=["vision", "language"],
        related_concepts=["alignment"],
        relation_requirements=["cross-modal fusion"],
        exclusion_concepts=["unrelated hardware"],
        domain="machine learning",
        time_range=TimeRange(start_year=2024, end_year=2026),
    )
    self.assertEqual(intent.time_range.end_year, 2026)


  def test_intent_limits_and_normalizes_terms(self) -> None:
    intent = ResearchIntent(research_question="q", required_concepts=["A", " a "])
    self.assertEqual(intent.required_concepts, ["A"])
    with self.assertRaises(ValueError):
        ResearchIntent(research_question="q", required_concepts=[])


  def test_time_range_order_is_validated(self) -> None:
    with self.assertRaises(ValueError):
        TimeRange(start_year=2026, end_year=2024)


  def test_no_time_range_is_allowed(self) -> None:
    self.assertIsNone(ResearchIntent(research_question="q", required_concepts=["q"]).time_range)

  def test_structured_planner_uses_injected_llm_output(self) -> None:
    expected = ResearchIntent(research_question="q", required_concepts=["vision"], relation_requirements=["fusion"])

    class FakeLLM:
      def generate_structured(self, **kwargs):
        self.kwargs = kwargs
        return expected

    planner = StructuredLLMResearchIntentPlanner(FakeLLM())
    self.assertEqual(planner.plan("q"), expected)
