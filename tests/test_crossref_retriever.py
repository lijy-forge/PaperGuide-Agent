"""Crossref adapter: the source that answers when the others refuse."""

import json
import unittest
from io import BytesIO

from paperguide.adapters import CrossrefClient, CrossrefConfig, CrossrefMapper
from paperguide.domain import FullTextStatus, PaperSource


def _response(payload: dict):
    class _Ctx:
        def __enter__(self_inner):
            return BytesIO(json.dumps(payload).encode("utf-8"))

        def __exit__(self_inner, *args):
            return False

    return lambda request, timeout=None: _Ctx()


_WORK = {
    "DOI": "10.1109/TMC.2024.3425723",
    "title": ["Hybrid Deep Reinforcement Learning-Based Task Offloading"],
    "container-title": ["IEEE Transactions on Mobile Computing"],
    "author": [{"given": "Wei", "family": "Zhang"}, {"name": "Some Lab"}],
    "abstract": "<jats:p>We study <jats:italic>offloading</jats:italic> &amp; more.</jats:p>",
    "published-print": {"date-parts": [[2024, 7]]},
    "is-referenced-by-count": 12,
    "type": "journal-article",
}


class CrossrefMapperTests(unittest.TestCase):
    def test_maps_the_fields_the_pipeline_matches_on(self) -> None:
        paper = CrossrefMapper.map_work(_WORK)

        self.assertEqual(paper.doi, "10.1109/tmc.2024.3425723")
        self.assertEqual(paper.publication_year, 2024)
        self.assertEqual(paper.venue, "IEEE Transactions on Mobile Computing")
        self.assertEqual(paper.citation_count, 12)
        self.assertEqual(paper.sources, [PaperSource.CROSSREF])

    def test_jats_markup_is_stripped_from_the_abstract(self) -> None:
        # Left in place the tag names become matchable text, and the gate
        # scores a paper on words its authors never wrote.
        abstract = CrossrefMapper.map_work(_WORK).abstract

        self.assertEqual(abstract, "We study offloading & more.")

    def test_an_organisation_author_is_kept(self) -> None:
        names = [author.full_name for author in CrossrefMapper.map_work(_WORK).authors]

        self.assertEqual(names, ["Wei Zhang", "Some Lab"])

    def test_no_pdf_is_claimed(self) -> None:
        # Crossref registers metadata, never files. Claiming a PDF would send
        # the downloader at a landing page and record a failure.
        paper = CrossrefMapper.map_work(_WORK)

        self.assertIsNone(paper.pdf_url)
        self.assertIs(paper.full_text_status, FullTextStatus.UNAVAILABLE)

    def test_a_year_only_record_does_not_invent_a_day(self) -> None:
        paper = CrossrefMapper.map_work({**_WORK, "published-print": {"date-parts": [[2019]]}})

        self.assertEqual(paper.publication_year, 2019)
        self.assertEqual(paper.published_at.date().isoformat(), "2019-01-01")

    def test_a_record_without_a_title_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CrossrefMapper.map_work({"DOI": "10.1/x"})


class CrossrefClientTests(unittest.TestCase):
    def test_component_records_are_filtered_out_by_the_request(self) -> None:
        # Unfiltered, a search returns figures and supplements deposited under
        # their own DOI; measured once, six of ten results were components.
        client = CrossrefClient()
        url = client._build_url("task offloading", 10)

        self.assertIn("type%3Ajournal-article", url)
        self.assertIn("type%3Aproceedings-article", url)

    def test_the_contact_address_reaches_both_places_crossref_reads(self) -> None:
        client = CrossrefClient(CrossrefConfig(mailto="someone@example.com"))

        self.assertIn("mailto=someone%40example.com", client._build_url("q", 3))
        self.assertIn("mailto:someone@example.com", client._request_user_agent())

    def test_one_unusable_record_does_not_discard_the_page(self) -> None:
        client = CrossrefClient(
            opener=_response({"message": {"items": [{"DOI": "10.1/x"}, _WORK]}})
        )

        papers = client.search("task offloading", max_results=5)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].publication_year, 2024)

    def test_an_empty_query_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            CrossrefClient().search("   ")
