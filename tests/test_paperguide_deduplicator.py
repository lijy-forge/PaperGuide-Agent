"""Unit tests for PaperGuide paper matching and deduplication."""

import unittest

from paperguide.domain import Author, FullTextStatus, PaperCandidate, PaperSource
from paperguide.services import DeduplicationResult, PaperDeduplicator, PaperMatcher


def make_candidate(**overrides) -> PaperCandidate:
    values = {
        "title": "YOLO-SLAM: Semantic Mapping in Dynamic Environments",
        "normalized_title": "stale input value",
        "abstract": None,
        "authors": [
            Author(
                full_name="John Smith",
                normalized_name="john smith",
                affiliations=["Robotics Lab"],
            )
        ],
        "publication_year": 2025,
        "venue": None,
        "doi": None,
        "arxiv_id": None,
        "semantic_scholar_id": None,
        "openalex_id": None,
        "sources": [PaperSource.WEB],
        "landing_page_url": None,
        "pdf_url": None,
        "citation_count": None,
        "full_text_status": FullTextStatus.UNKNOWN,
        "relevance_score": None,
        "selection_reason": None,
    }
    values.update(overrides)
    return PaperCandidate(**values)


class TestPaperMatcher(unittest.TestCase):
    def setUp(self):
        self.matcher = PaperMatcher()

    def test_same_doi_matches(self):
        result = self.matcher.match(
            make_candidate(doi="doi:10.1000/ABC"),
            make_candidate(doi="https://doi.org/10.1000/abc"),
        )

        self.assertTrue(result.is_match)
        self.assertEqual(result.matched_by, ["doi"])
        self.assertGreaterEqual(result.confidence, 0.95)

    def test_same_arxiv_id_matches(self):
        result = self.matcher.match(
            make_candidate(arxiv_id="arXiv:2401.12345v2"),
            make_candidate(arxiv_id="https://arxiv.org/abs/2401.12345"),
        )

        self.assertTrue(result.is_match)
        self.assertEqual(result.matched_by, ["arxiv_id"])

    def test_exact_normalized_title_authors_and_close_year_match(self):
        result = self.matcher.match(
            make_candidate(
                title="YOLO-SLAM: Semantic Mapping in Dynamic Environments",
                publication_year=2024,
            ),
            make_candidate(
                title="yolo slam semantic_mapping in dynamic environments!",
                publication_year=2025,
            ),
        )

        self.assertTrue(result.is_match)
        self.assertIn("normalized_title", result.matched_by)
        self.assertTrue(result.reasons)

    def test_similar_title_with_different_authors_does_not_match(self):
        result = self.matcher.match(
            make_candidate(),
            make_candidate(
                title="YOLO SLAM Semantic Mapping for Dynamic Environments",
                authors=[
                    Author(
                        full_name="Alice Chen",
                        normalized_name="alice chen",
                        affiliations=[],
                    )
                ],
            ),
        )

        self.assertFalse(result.is_match)
        self.assertTrue(any("Author overlap" in reason for reason in result.reasons))

    def test_fuzzy_title_matches_only_with_authors_and_year(self):
        result = self.matcher.match(
            make_candidate(
                title="Robust YOLO SLAM Semantic Mapping in Dynamic Environments"
            ),
            make_candidate(
                title="Robust YOLO-SLAM Semantic Mapping for Dynamic Environments"
            ),
        )

        self.assertTrue(result.is_match)
        self.assertIn("fuzzy_title", result.matched_by)

    def test_doi_conflict_blocks_title_based_matching(self):
        result = self.matcher.match(
            make_candidate(doi="10.1000/one"),
            make_candidate(doi="10.1000/two"),
        )

        self.assertFalse(result.is_match)
        self.assertTrue(any("DOI conflict" in reason for reason in result.reasons))

    def test_short_title_uses_stricter_rules(self):
        result = self.matcher.match(
            make_candidate(title="Deep SLAM", publication_year=2024),
            make_candidate(title="Deep-SLAM", publication_year=2025),
        )

        self.assertFalse(result.is_match)
        self.assertTrue(any("short title" in reason.lower() for reason in result.reasons))


class TestPaperDeduplicator(unittest.TestCase):
    def setUp(self):
        self.deduplicator = PaperDeduplicator()

    def test_three_sources_for_one_paper_merge_into_one(self):
        arxiv = make_candidate(
            title="YOLO-SLAM: Semantic Mapping in Dynamic Environments",
            doi="10.1000/yolo-slam",
            arxiv_id="2401.12345v2",
            sources=[PaperSource.ARXIV],
            abstract="Short abstract.",
            pdf_url="https://arxiv.org/pdf/2401.12345v2.pdf",
            full_text_status=FullTextStatus.AVAILABLE,
            citation_count=5,
        )
        semantic = make_candidate(
            title="YOLO-SLAM: Semantic Mapping in Dynamic Environments",
            doi="https://doi.org/10.1000/YOLO-SLAM",
            semantic_scholar_id="CorpusId:123",
            sources=[PaperSource.SEMANTIC_SCHOLAR],
            abstract="A substantially longer abstract describing the complete method.",
            citation_count=42,
            relevance_score=0.95,
        )
        openalex = make_candidate(
            title="YOLO SLAM: Semantic Mapping in Dynamic Environments",
            arxiv_id="https://arxiv.org/abs/2401.12345",
            semantic_scholar_id="corpusid:123",
            openalex_id="W123",
            sources=[PaperSource.OPENALEX],
            citation_count=30,
            full_text_status=FullTextStatus.UNAVAILABLE,
        )

        result = self.deduplicator.deduplicate([arxiv, semantic, openalex])

        self.assertEqual(result.original_count, 3)
        self.assertEqual(result.deduplicated_count, 1)
        self.assertEqual(len(result.merged_groups), 1)
        merged = result.papers[0]
        self.assertEqual(
            merged.sources,
            [
                PaperSource.ARXIV,
                PaperSource.SEMANTIC_SCHOLAR,
                PaperSource.OPENALEX,
            ],
        )
        self.assertEqual(merged.citation_count, 42)
        self.assertIs(merged.full_text_status, FullTextStatus.AVAILABLE)
        self.assertEqual(merged.relevance_score, 0.95)
        self.assertEqual(merged.normalized_title, "yolo slam semantic mapping in dynamic environments")

    def test_authors_and_affiliations_are_merged(self):
        left = make_candidate(
            doi="10.1000/authors",
            authors=[
                Author(
                    full_name="John Smith",
                    normalized_name="john smith",
                    affiliations=["Robotics Lab"],
                )
            ],
        )
        right = make_candidate(
            doi="10.1000/authors",
            authors=[
                Author(
                    full_name="Smith, John",
                    normalized_name="john smith",
                    affiliations=["AI Institute", "Robotics Lab"],
                ),
                Author(
                    full_name="张伟",
                    normalized_name="张伟",
                    affiliations=["智能系统实验室"],
                ),
            ],
        )

        merged = self.deduplicator.deduplicate([left, right]).papers[0]

        self.assertEqual(len(merged.authors), 2)
        john = next(author for author in merged.authors if author.normalized_name == "john smith")
        self.assertEqual(john.affiliations, ["AI Institute", "Robotics Lab"])

    def test_canonical_selection_is_not_dependent_on_input_order(self):
        sparse = make_candidate(
            semantic_scholar_id="paper-1",
            sources=[PaperSource.SEMANTIC_SCHOLAR],
        )
        complete = make_candidate(
            doi="10.1000/canonical",
            arxiv_id="2401.12345",
            semantic_scholar_id="paper-1",
            openalex_id="W123",
            abstract="Complete abstract.",
            venue="ICRA",
            pdf_url="https://arxiv.org/pdf/2401.12345.pdf",
            sources=[PaperSource.ARXIV, PaperSource.OPENALEX],
        )

        forward = self.deduplicator.deduplicate([sparse, complete])
        reverse = self.deduplicator.deduplicate([complete, sparse])

        self.assertEqual(forward.papers[0].id, complete.id)
        self.assertEqual(reverse.papers[0].id, complete.id)

    def test_explicit_doi_conflict_creates_warning_when_stable_id_matches(self):
        left = make_candidate(
            doi="10.1000/one",
            semantic_scholar_id="same-paper",
        )
        right = make_candidate(
            doi="10.1000/two",
            semantic_scholar_id="same-paper",
            abstract="More complete metadata selects this record as canonical.",
        )

        result = self.deduplicator.deduplicate([left, right])

        self.assertEqual(result.deduplicated_count, 1)
        self.assertTrue(any("Conflicting DOI" in warning for warning in result.warnings))
        self.assertEqual(result.papers[0].doi, "10.1000/two")

    def test_non_duplicate_papers_remain_independent(self):
        left = make_candidate(
            title="YOLO-SLAM for Dynamic Scenes",
            doi="10.1000/left",
        )
        right = make_candidate(
            title="Neural Radiance Fields for Reconstruction",
            doi="10.1000/right",
        )

        result = self.deduplicator.deduplicate([left, right])

        self.assertEqual(result.original_count, 2)
        self.assertEqual(result.deduplicated_count, 2)
        self.assertEqual(result.merged_groups, [])

    def test_empty_list_returns_empty_result(self):
        result = self.deduplicator.deduplicate([])

        self.assertEqual(result.papers, [])
        self.assertEqual(result.original_count, 0)
        self.assertEqual(result.deduplicated_count, 0)
        self.assertEqual(result.warnings, [])

    def test_deduplication_does_not_mutate_inputs(self):
        left = make_candidate(doi="10.1000/immutable", abstract="Short.")
        right = make_candidate(
            doi="10.1000/immutable",
            abstract="A much longer abstract from another source.",
        )
        before_left = left.model_dump(mode="json")
        before_right = right.model_dump(mode="json")

        self.deduplicator.deduplicate([left, right])

        self.assertEqual(left.model_dump(mode="json"), before_left)
        self.assertEqual(right.model_dump(mode="json"), before_right)

    def test_result_json_round_trip(self):
        left = make_candidate(doi="10.1000/json", sources=[PaperSource.ARXIV])
        right = make_candidate(
            doi="doi:10.1000/json",
            sources=[PaperSource.OPENALEX],
        )
        result = self.deduplicator.deduplicate([left, right])

        restored = DeduplicationResult.model_validate_json(result.model_dump_json())

        self.assertEqual(restored, result)


if __name__ == "__main__":
    unittest.main()
