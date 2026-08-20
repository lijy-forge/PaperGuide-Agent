"""Unit tests for the multi-retriever PaperPilot search pipeline."""

import unittest

from paperpilot.adapters import RetrieverProtocol
from paperpilot.domain import (
    Author,
    FullTextStatus,
    PaperCandidate,
    PaperSource,
    ResearchConfig,
)
from paperpilot.pipeline import PaperSearchPipeline, SearchResult


def make_paper(
    title: str,
    source: PaperSource,
    *,
    doi: str | None = None,
    relevance_score: float | None = None,
    publication_year: int | None = 2025,
) -> PaperCandidate:
    return PaperCandidate(
        title=title,
        normalized_title=title.casefold(),
        abstract=None,
        authors=[
            Author(
                full_name="Ada Researcher",
                normalized_name="ada researcher",
                affiliations=[],
            )
        ],
        publication_year=publication_year,
        venue=None,
        doi=doi,
        arxiv_id=None,
        semantic_scholar_id=None,
        openalex_id=None,
        sources=[source],
        landing_page_url=None,
        pdf_url=None,
        citation_count=None,
        full_text_status=FullTextStatus.UNKNOWN,
        relevance_score=relevance_score,
        selection_reason=None,
    )


class MockRetriever:
    """Configurable in-memory retriever used by pipeline tests."""

    def __init__(
        self,
        source: PaperSource,
        papers: list[PaperCandidate] | None = None,
        error: Exception | None = None,
    ):
        self.source = source
        self.papers = papers or []
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def search(
        self, query: str, max_results: int = 10
    ) -> list[PaperCandidate]:
        self.calls.append((query, max_results))
        if self.error:
            raise self.error
        return list(self.papers)


def make_config(
    *,
    max_papers: int = 10,
    sources: list[PaperSource] | None = None,
) -> ResearchConfig:
    return ResearchConfig(
        question="Analyze YOLO and SLAM research",
        max_papers=max_papers,
        sources=sources
        if sources is not None
        else [PaperSource.ARXIV, PaperSource.SEMANTIC_SCHOLAR],
    )


class TestPaperSearchPipeline(unittest.TestCase):
    def test_two_retrievers_return_results(self):
        arxiv = MockRetriever(
            PaperSource.ARXIV,
            [make_paper("Arxiv Paper", PaperSource.ARXIV, doi="10.1000/a")],
        )
        semantic = MockRetriever(
            PaperSource.SEMANTIC_SCHOLAR,
            [
                make_paper(
                    "Semantic Paper",
                    PaperSource.SEMANTIC_SCHOLAR,
                    doi="10.1000/b",
                )
            ],
        )

        result = PaperSearchPipeline([arxiv, semantic]).search(make_config())

        self.assertEqual(len(result.papers), 2)
        self.assertEqual(result.total_found, 2)
        self.assertEqual(result.total_after_dedup, 2)

    def test_duplicate_papers_are_merged(self):
        arxiv = MockRetriever(
            PaperSource.ARXIV,
            [make_paper("Shared Paper", PaperSource.ARXIV, doi="10.1000/shared")],
        )
        semantic = MockRetriever(
            PaperSource.SEMANTIC_SCHOLAR,
            [
                make_paper(
                    "Shared Paper",
                    PaperSource.SEMANTIC_SCHOLAR,
                    doi="https://doi.org/10.1000/SHARED",
                )
            ],
        )

        result = PaperSearchPipeline([arxiv, semantic]).search(make_config())

        self.assertEqual(result.total_found, 2)
        self.assertEqual(result.total_after_dedup, 1)
        self.assertEqual(len(result.papers), 1)
        self.assertEqual(
            result.papers[0].sources,
            [PaperSource.ARXIV, PaperSource.SEMANTIC_SCHOLAR],
        )

    def test_one_retriever_failure_returns_partial_results(self):
        arxiv = MockRetriever(
            PaperSource.ARXIV,
            [make_paper("Available Paper", PaperSource.ARXIV)],
        )
        semantic = MockRetriever(
            PaperSource.SEMANTIC_SCHOLAR,
            error=TimeoutError("timed out"),
        )

        result = PaperSearchPipeline([arxiv, semantic]).search(make_config())

        self.assertEqual(len(result.papers), 1)
        self.assertEqual(result.source_results, {"arxiv": 1})
        self.assertEqual(result.source_errors, {"semantic_scholar": "timed out"})
        self.assertTrue(any("semantic_scholar" in warning for warning in result.warnings))

    def test_all_retriever_failures_return_errors_and_no_papers(self):
        pipeline = PaperSearchPipeline(
            [
                MockRetriever(PaperSource.ARXIV, error=RuntimeError("arxiv down")),
                MockRetriever(
                    PaperSource.SEMANTIC_SCHOLAR,
                    error=TimeoutError("semantic timeout"),
                ),
            ]
        )

        result = pipeline.search(make_config())

        self.assertEqual(result.papers, [])
        self.assertEqual(result.total_found, 0)
        self.assertEqual(result.total_after_dedup, 0)
        self.assertEqual(set(result.source_errors), {"arxiv", "semantic_scholar"})
        self.assertEqual(len(result.warnings), 2)

    def test_max_papers_limits_relevance_sorted_results(self):
        papers = [
            make_paper(
                "Unscored",
                PaperSource.ARXIV,
                doi="10.1000/unscored",
            ),
            make_paper(
                "Medium",
                PaperSource.ARXIV,
                doi="10.1000/medium",
                relevance_score=0.5,
            ),
            make_paper(
                "Highest",
                PaperSource.ARXIV,
                doi="10.1000/high",
                relevance_score=0.95,
            ),
        ]
        pipeline = PaperSearchPipeline([MockRetriever(PaperSource.ARXIV, papers)])

        result = pipeline.search(
            make_config(max_papers=2, sources=[PaperSource.ARXIV])
        )

        self.assertEqual([paper.title for paper in result.papers], ["Highest", "Medium"])
        self.assertEqual(result.total_after_dedup, 3)

    def test_source_results_are_recorded(self):
        arxiv = MockRetriever(
            PaperSource.ARXIV,
            [
                make_paper("A1", PaperSource.ARXIV),
                make_paper("A2", PaperSource.ARXIV),
            ],
        )
        semantic = MockRetriever(PaperSource.SEMANTIC_SCHOLAR, [])

        result = PaperSearchPipeline([arxiv, semantic]).search(make_config())

        self.assertEqual(
            result.source_results,
            {"arxiv": 2, "semantic_scholar": 0},
        )

    def test_search_result_json_round_trip(self):
        pipeline = PaperSearchPipeline(
            [
                MockRetriever(
                    PaperSource.ARXIV,
                    [make_paper("Serializable", PaperSource.ARXIV)],
                )
            ]
        )
        result = pipeline.search(make_config(sources=[PaperSource.ARXIV]))

        restored = SearchResult.model_validate_json(result.model_dump_json())

        self.assertEqual(restored, result)

    def test_mock_retriever_satisfies_protocol(self):
        retriever = MockRetriever(PaperSource.ARXIV)

        self.assertIsInstance(retriever, RetrieverProtocol)
        PaperSearchPipeline([retriever])

    def test_research_config_is_not_modified(self):
        config = make_config(max_papers=7)
        before = config.model_dump(mode="json")
        retriever = MockRetriever(PaperSource.ARXIV)

        PaperSearchPipeline([retriever]).search(config)

        self.assertEqual(config.model_dump(mode="json"), before)
        self.assertEqual(
            retriever.calls,
            [("Analyze YOLO and SLAM research", 7)],
        )

    def test_year_scope_overfetches_then_filters_candidates(self):
        retriever = MockRetriever(
            PaperSource.ARXIV,
            [
                make_paper("Out of range", PaperSource.ARXIV, publication_year=2023),
                make_paper("In range", PaperSource.ARXIV, publication_year=2025),
                make_paper("Unknown year", PaperSource.ARXIV, publication_year=None),
            ],
        )
        config = ResearchConfig(
            question="Analyze research from 2024 to 2026",
            start_year=2024,
            end_year=2026,
            max_papers=1,
            sources=[PaperSource.ARXIV],
        )

        result = PaperSearchPipeline([retriever]).search(config)

        self.assertEqual(retriever.calls, [(config.question, 5)])
        self.assertEqual([paper.title for paper in result.papers], ["In range"])

    def test_empty_retriever_result_is_successful(self):
        result = PaperSearchPipeline(
            [MockRetriever(PaperSource.ARXIV, [])]
        ).search(make_config(sources=[PaperSource.ARXIV]))

        self.assertEqual(result.papers, [])
        self.assertEqual(result.source_results, {"arxiv": 0})
        self.assertEqual(result.source_errors, {})
        self.assertEqual(result.warnings, [])

    def test_unconfigured_retriever_is_not_called(self):
        arxiv = MockRetriever(PaperSource.ARXIV)
        semantic = MockRetriever(PaperSource.SEMANTIC_SCHOLAR)

        PaperSearchPipeline([arxiv, semantic]).search(
            make_config(sources=[PaperSource.ARXIV])
        )

        self.assertEqual(len(arxiv.calls), 1)
        self.assertEqual(semantic.calls, [])


if __name__ == "__main__":
    unittest.main()
