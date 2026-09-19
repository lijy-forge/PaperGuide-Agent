"""A rejected run must name the reason as specifically as the run allows."""

import unittest

from paperguide.application.service import ResearchApplicationService
from paperguide.pipeline.search_pipeline import PaperSearchPipeline


class _Quality:
    def __init__(self, reference_entry_count: int) -> None:
        self.reference_entry_count = reference_entry_count


class RejectionCodeTests(unittest.TestCase):
    def test_a_year_scope_that_emptied_retrieval_is_named(self) -> None:
        code = ResearchApplicationService._rejection_code(
            _Quality(0), {"warnings": [PaperSearchPipeline.YEAR_SCOPE_EXCLUDED_ALL]}
        )
        self.assertEqual(code, "NO_PAPERS_IN_TIME_RANGE")

    def test_no_references_without_a_year_signal_is_the_general_case(self) -> None:
        code = ResearchApplicationService._rejection_code(_Quality(0), {"warnings": []})
        self.assertEqual(code, "NO_EVIDENCE_FOR_QUESTION")

    def test_a_report_with_references_failed_some_other_contract(self) -> None:
        # References exist, so the reader cannot fix this by widening a range;
        # reporting the year code here would send them to the wrong place.
        code = ResearchApplicationService._rejection_code(
            _Quality(3), {"warnings": [PaperSearchPipeline.YEAR_SCOPE_EXCLUDED_ALL]}
        )
        self.assertEqual(code, "REPORT_QUALITY_REJECTED")

    def test_a_state_without_warnings_does_not_raise(self) -> None:
        self.assertEqual(
            ResearchApplicationService._rejection_code(_Quality(0), {}),
            "NO_EVIDENCE_FOR_QUESTION",
        )


class YearScopeSignalTests(unittest.TestCase):
    def test_the_pipeline_reports_a_range_that_excluded_everything(self) -> None:
        from paperguide.domain import (
            FullTextStatus,
            PaperCandidate,
            PaperSource,
            ResearchConfig,
        )

        class _Retriever:
            source = PaperSource.ARXIV

            def search(self, query: str, max_results: int = 10):
                return [
                    PaperCandidate(
                        title="An Older Paper",
                        normalized_title="an older paper",
                        authors=[],
                        publication_year=2015,
                        sources=[PaperSource.ARXIV],
                        full_text_status=FullTextStatus.UNAVAILABLE,
                    )
                ]

        result = PaperSearchPipeline([_Retriever()]).search(
            ResearchConfig(
                question="anything",
                sources=[PaperSource.ARXIV],
                start_year=2024,
                end_year=2026,
            )
        )

        self.assertEqual(result.papers, [])
        self.assertIn(PaperSearchPipeline.YEAR_SCOPE_EXCLUDED_ALL, result.warnings)

    def test_no_signal_when_the_sources_simply_found_nothing(self) -> None:
        from paperguide.domain import PaperSource, ResearchConfig

        class _Empty:
            source = PaperSource.ARXIV

            def search(self, query: str, max_results: int = 10):
                return []

        result = PaperSearchPipeline([_Empty()]).search(
            ResearchConfig(
                question="anything",
                sources=[PaperSource.ARXIV],
                start_year=2024,
                end_year=2026,
            )
        )

        # Nothing was retrieved, so the range excluded nothing and blaming it
        # would point the reader at the wrong thing.
        self.assertNotIn(PaperSearchPipeline.YEAR_SCOPE_EXCLUDED_ALL, result.warnings)
