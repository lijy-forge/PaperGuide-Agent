"""Unit tests for deterministic PaperGuide metadata normalization."""

import unittest

from paperguide.services import MetadataNormalizer


class TestMetadataNormalizer(unittest.TestCase):
    def test_title_normalization(self):
        self.assertEqual(
            MetadataNormalizer.normalize_title(
                "  YOLO-SLAM:   Semantic_Mapping!  "
            ),
            "yolo slam semantic mapping",
        )
        self.assertEqual(
            MetadataNormalizer.normalize_title("视觉—SLAM：研究进展"),
            "视觉 slam 研究进展",
        )

    def test_common_doi_forms_normalize_to_the_same_value(self):
        expected = "10.1000/xyz123"
        values = (
            "10.1000/XYZ123",
            "doi:10.1000/XYZ123",
            "https://doi.org/10.1000/XYZ123",
            "http://dx.doi.org/10.1000/XYZ123",
        )

        for value in values:
            with self.subTest(value=value):
                self.assertEqual(MetadataNormalizer.normalize_doi(value), expected)

    def test_doi_trailing_punctuation_is_removed(self):
        self.assertEqual(
            MetadataNormalizer.normalize_doi("doi:10.1000/XYZ123)."),
            "10.1000/xyz123",
        )
        self.assertIsNone(MetadataNormalizer.normalize_doi("not-a-doi"))

    def test_arxiv_url_version_and_pdf_forms_are_normalized(self):
        values = (
            "2401.12345v2",
            "arXiv:2401.12345",
            "https://arxiv.org/abs/2401.12345v3",
            "https://arxiv.org/pdf/2401.12345v2.pdf",
        )

        for value in values:
            with self.subTest(value=value):
                self.assertEqual(
                    MetadataNormalizer.normalize_arxiv_id(value), "2401.12345"
                )

    def test_legacy_arxiv_id_is_supported(self):
        self.assertEqual(
            MetadataNormalizer.normalize_arxiv_id("arXiv:cs/9901001v2"),
            "cs/9901001",
        )

    def test_english_author_name_normalization(self):
        self.assertEqual(
            MetadataNormalizer.normalize_author_name("  Smith,   John  "),
            "john smith",
        )
        self.assertEqual(
            MetadataNormalizer.normalize_author_name("John   Smith"),
            "john smith",
        )

    def test_chinese_author_name_is_preserved(self):
        self.assertEqual(MetadataNormalizer.normalize_author_name("  张   伟 "), "张 伟")

    def test_url_fragment_is_removed_and_query_is_preserved(self):
        self.assertEqual(
            MetadataNormalizer.normalize_url(
                " HTTPS://Example.COM/paper?id=42#experiments "
            ),
            "https://example.com/paper?id=42",
        )

    def test_doi_and_arxiv_urls_receive_source_specific_normalization(self):
        self.assertEqual(
            MetadataNormalizer.normalize_url(
                "http://DX.DOI.org/10.1000/XYZ123#section"
            ),
            "https://doi.org/10.1000/xyz123",
        )
        self.assertEqual(
            MetadataNormalizer.normalize_url(
                "http://www.arxiv.org/pdf/2401.12345v2.pdf?download=1#page=2"
            ),
            "https://arxiv.org/pdf/2401.12345.pdf?download=1",
        )


if __name__ == "__main__":
    unittest.main()
