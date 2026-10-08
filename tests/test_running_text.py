"""Tests for removing the lines a publisher repeats on every page.

The risk runs both ways: leaving boilerplate in severs sentences that cross a
page break, and removing too eagerly deletes the paper's own words. Each test
names which of the two it guards.
"""

import unittest

from paperguide.document.models import Page
from paperguide.document.running_text import find_running_shapes, strip_running_text


#: Distinct wording per page. Bodies that differ only by a number would be
#: identical once digits are blanked, which is a property of the fixture and
#: not of real prose — and it would hide what these tests mean to check.
_BODY = [
    "We formulate the offloading problem under a delay budget.",
    "The solver alternates between allocation and scheduling.",
    "Experiments use a testbed of heterogeneous edge nodes.",
    "Latency falls once cooperative transmission is enabled.",
    "Energy behaves differently when the uplink saturates.",
    "We close by discussing threats to validity and scope.",
    "An appendix lists the hyperparameters used throughout.",
    "Acknowledgements name the funding bodies involved.",
]


def body(page_number: int) -> str:
    return _BODY[(page_number - 1) % len(_BODY)]


def paginated(count: int, *, header: str | None = None, footer: str | None = None):
    pages = []
    for number in range(1, count + 1):
        lines = []
        if header is not None:
            lines.append(header.replace("#", str(number)))
        lines.append(body(number))
        if footer is not None:
            lines.append(footer.replace("#", str(number)))
        pages.append(Page(page_number=number, text="\n".join(lines)))
    return pages


class TestFindRunningShapes(unittest.TestCase):
    def test_a_repeated_footer_is_detected(self):
        shapes = find_running_shapes(paginated(6, footer="Licensed under CC BY"))

        self.assertIn("Licensed under CC BY", shapes)

    def test_a_page_number_counts_as_one_shape(self):
        """"Page 3" and "Page 4" are the same furniture, not two lines."""
        shapes = find_running_shapes(paginated(6, footer="Page # of 6"))

        self.assertIn("Page # of #", shapes)

    def test_a_short_document_is_left_alone(self):
        """Two pages cannot distinguish a header from a coincidence."""
        self.assertEqual(find_running_shapes(paginated(2, footer="Repeated")), set())

    def test_a_line_on_a_minority_of_pages_is_not_furniture(self):
        pages = paginated(8)
        pages[0] = pages[0].model_copy(
            update={"text": "Occasional note\n" + pages[0].text}
        )
        pages[1] = pages[1].model_copy(
            update={"text": "Occasional note\n" + pages[1].text}
        )

        self.assertNotIn("Occasional note", find_running_shapes(pages))


class TestStripRunningText(unittest.TestCase):
    def test_the_footer_goes_and_the_body_stays(self):
        pages, removed = strip_running_text(
            paginated(6, footer="Licensed under CC BY")
        )

        self.assertTrue(all("Licensed" not in page.text for page in pages))
        self.assertTrue(all(body(page.page_number) in page.text for page in pages))
        self.assertEqual(len(removed), 6)

    def test_a_sentence_across_a_page_break_becomes_contiguous(self):
        """The reason this exists: boilerplate severs a spanning sentence."""
        pages = [
            Page(page_number=1, text="The problem was decomposed into two\nBOILERPLATE"),
            Page(page_number=2, text="BOILERPLATE\nsub-problems solved iteratively."),
            Page(page_number=3, text="BOILERPLATE\nUnrelated third page body text."),
        ]

        cleaned, _ = strip_running_text(pages)
        joined = "\n".join(page.text for page in cleaned)

        self.assertIn(
            "The problem was decomposed into two\nsub-problems solved iteratively.",
            joined,
        )

    def test_a_repeated_line_inside_the_body_is_kept(self):
        """Only the top and bottom are furniture; the middle is the paper."""
        pages = [
            Page(
                page_number=number,
                text="\n".join(
                    [
                        f"Head {number}",
                        "opening sentence",
                        "we evaluate on KITTI",
                        "closing sentence",
                        f"Foot {number}",
                    ]
                ),
            )
            for number in range(1, 7)
        ]

        cleaned, _ = strip_running_text(pages)

        self.assertTrue(
            all("we evaluate on KITTI" in page.text for page in cleaned)
        )

    def test_a_page_is_never_gutted(self):
        """A rule that wants most of a page is wrong, so it is not applied."""
        pages = [
            Page(page_number=number, text="Repeated\nRepeated\nRepeated")
            for number in range(1, 7)
        ]

        cleaned, removed = strip_running_text(pages)

        self.assertTrue(all(page.text for page in cleaned))
        self.assertEqual(removed, [])

    def test_removed_lines_are_returned_for_the_record(self):
        """A caller must be able to check what was taken out, not assume."""
        _, removed = strip_running_text(paginated(5, header="Gui and Wang"))

        self.assertEqual(removed, ["Gui and Wang"] * 5)

    def test_pages_without_furniture_are_unchanged(self):
        pages = paginated(5)

        cleaned, removed = strip_running_text(pages)

        self.assertEqual([page.text for page in cleaned], [page.text for page in pages])
        self.assertEqual(removed, [])


if __name__ == "__main__":
    unittest.main()
