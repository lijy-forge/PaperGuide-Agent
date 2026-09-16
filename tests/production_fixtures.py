"""Shared fixtures for exercising the production export path.

The export authenticity guard in ``paperguide.reporting.survey`` fails closed
when placeholder records reach a production export: ``example.invalid`` URLs,
``demo.NNNN`` arXiv ids and "Offline Demo" venues all mark a record as
synthetic. The offline demo seed is deliberately built from those placeholders,
so tests that drive the production profile need seed papers re-stamped with
resolvable provenance.
"""

__all__ = ["production_provenance"]


def production_provenance(papers):
    """Return the demo papers with production-shaped provenance fields."""

    upgraded = []
    for index, paper in enumerate(papers, start=1):
        arxiv_id = f"2107.{index:05d}"
        upgraded.append(
            paper.model_copy(
                update={
                    "venue": "IEEE International Conference on Robotics and Automation",
                    "arxiv_id": arxiv_id,
                    "doi": f"10.1109/ICRA.2021.{index:07d}",
                    "landing_page_url": f"https://arxiv.org/abs/{arxiv_id}",
                    "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
                }
            )
        )
    return upgraded
