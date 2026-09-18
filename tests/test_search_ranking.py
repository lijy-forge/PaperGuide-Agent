"""Candidates must be ranked by the question, not by source order."""

from urllib.parse import unquote_plus

from paperguide.adapters import ArxivClient
from paperguide.domain import FullTextStatus, PaperCandidate, PaperSource
from paperguide.pipeline.ranking import content_terms, rank_by_question


def make_paper(title: str, abstract: str = "", year: int = 2020) -> PaperCandidate:
    return PaperCandidate(
        title=title,
        normalized_title=title.casefold(),
        abstract=abstract,
        authors=[],
        publication_year=year,
        sources=[PaperSource.ARXIV],
        arxiv_id=f"0000.{abs(hash(title)) % 10000:04d}",
        full_text_status=FullTextStatus.UNKNOWN,
    )


def _search_query(client: ArxivClient, question: str) -> str:
    return unquote_plus(client._build_url(question, 10).split("search_query=")[1].split("&")[0])


def test_stopwords_are_not_required_terms():
    """'of' and 'for' carry no topic but, when required, match nothing."""

    query = _search_query(ArxivClient(), "prediction of yield stress for suspensions")
    assert "all:\"of\"" not in query
    assert "all:\"for\"" not in query
    assert 'all:"yield"' in query
    assert 'all:"suspensions"' in query


def test_a_short_query_stays_conjunctive_but_a_long_one_widens():
    """Two terms can be required; six cannot, or the search returns nothing."""

    client = ArxivClient()
    assert " AND " in _search_query(client, "YOLO SLAM")
    assert " OR " in _search_query(
        client, "yield stress prediction composite propellant slurry rheology"
    )


def test_candidates_are_ordered_by_question_relevance():
    papers = [
        make_paper("Unrelated work on galaxy formation"),
        make_paper("Yield stress of concentrated suspensions", "rheology of dense suspensions"),
        make_paper("A note on suspensions"),
    ]

    ranked = rank_by_question(papers, "yield stress of concentrated suspensions")

    assert ranked[0].title == "Yield stress of concentrated suspensions"
    assert ranked[-1].title == "Unrelated work on galaxy formation"


def test_ranking_is_deterministic_when_nothing_matches():
    """An unmatched query must still give a stable order, not an arbitrary one."""

    papers = [make_paper("Beta study", year=2020), make_paper("Alpha study", year=2021)]

    first = rank_by_question(papers, "completely unrelated topic")
    second = rank_by_question(list(reversed(papers)), "completely unrelated topic")

    assert [paper.title for paper in first] == [paper.title for paper in second]
    # Ties fall back to the newer paper.
    assert first[0].title == "Alpha study"


def test_content_terms_drop_stopwords_and_keep_cjk():
    assert content_terms("the yield stress of a suspension") == ["yield", "stress", "suspension"]
    assert content_terms("屈服应力") == ["屈", "服", "应", "力"]
