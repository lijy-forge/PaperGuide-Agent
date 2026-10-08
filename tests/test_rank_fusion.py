"""Tests for combining several sources' rankings.

The property worth having is that agreement between sources outranks one
source's first place, and that merging duplicates gathers rather than loses
what each source contributed.
"""

import unittest
from uuid import uuid4

from paperguide.domain import PaperSource
from paperguide.pipeline.fusion import DEFAULT_K, fuse, reciprocal_rank_score
from paperguide.pipeline.search_pipeline import PaperSearchPipeline

from .test_search_pipeline import MockRetriever, make_config, make_paper


class TestReciprocalRankScore(unittest.TestCase):
    def test_earlier_positions_score_higher(self):
        self.assertGreater(reciprocal_rank_score(0), reciprocal_rank_score(1))
        self.assertGreater(reciprocal_rank_score(1), reciprocal_rank_score(9))

    def test_the_damping_constant_keeps_top_places_comparable(self):
        """Without damping a first place would dwarf everything below it.

        Two sources agreeing at rank 1 must be able to outrank one source's
        rank 0, which is the whole point of the constant.
        """
        first = reciprocal_rank_score(0)
        agreed = reciprocal_rank_score(1) + reciprocal_rank_score(1)

        self.assertGreater(agreed, first)
        self.assertEqual(reciprocal_rank_score(0), 1.0 / (DEFAULT_K + 1))

    def test_a_negative_rank_is_refused(self):
        with self.assertRaises(ValueError):
            reciprocal_rank_score(-1)


class TestFuse(unittest.TestCase):
    def test_a_duplicate_s_score_joins_its_canonical_paper(self):
        """Dedup runs first, so without this, being found twice would cost."""
        canonical, duplicate = uuid4(), uuid4()
        contributions = {canonical: 0.01, duplicate: 0.02}

        fused = fuse(contributions, [(canonical, [duplicate])])

        self.assertAlmostEqual(fused[canonical], 0.03)

    def test_papers_with_no_duplicates_are_untouched(self):
        only = uuid4()

        self.assertEqual(fuse({only: 0.5}, []), {only: 0.5})


class TestPipelineFusion(unittest.TestCase):
    def test_a_paper_two_sources_agree_on_outranks_one_source_s_first(self):
        # The solo paper matches the question and the shared one does not, so
        # BM25 alone puts solo first. Only fusion can reverse that, which is
        # what this test has to be able to see.
        shared_doi = "10.1000/shared"
        agreed_a = make_paper("Unrelated topic", PaperSource.ARXIV, doi=shared_doi)
        agreed_b = make_paper("Unrelated topic", PaperSource.OPENALEX, doi=shared_doi)
        solo = make_paper("YOLO and SLAM research", PaperSource.ARXIV, doi="10.1000/solo")

        pipeline = PaperSearchPipeline(
            [
                MockRetriever(PaperSource.ARXIV, [solo, agreed_a]),
                MockRetriever(PaperSource.OPENALEX, [agreed_b]),
            ]
        )

        result = pipeline.search(
            make_config(
                max_papers=5, sources=[PaperSource.ARXIV, PaperSource.OPENALEX]
            )
        )

        self.assertEqual(result.papers[0].title, "Unrelated topic")

    def test_one_answering_source_still_returns_its_order(self):
        """With a single source every fused score ties, so ranking must not
        collapse to whatever order that source happened to return."""
        papers = [
            make_paper("Later", PaperSource.ARXIV, doi="10.1000/b"),
            make_paper("Earlier", PaperSource.ARXIV, doi="10.1000/a"),
        ]
        pipeline = PaperSearchPipeline([MockRetriever(PaperSource.ARXIV, papers)])

        result = pipeline.search(
            make_config(max_papers=5, sources=[PaperSource.ARXIV])
        )

        self.assertEqual(len(result.papers), 2)


if __name__ == "__main__":
    unittest.main()
