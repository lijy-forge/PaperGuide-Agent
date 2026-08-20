"""Deterministic, copyright-safe seed data for the offline demonstration."""

from dataclasses import dataclass
from uuid import UUID, NAMESPACE_URL, uuid5

from paperpilot.document import (
    Document,
    DocumentIngestionResult,
    IngestionStatus,
    Page,
    PaperIngestionItem,
    Section,
)
from paperpilot.domain import (
    Author,
    FullTextStatus,
    PaperCandidate,
    PaperSource,
)

DEMO_QUESTION = "YOLO与视觉SLAM融合研究进展"


def _demo_uuid(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://paperpilot.local/demo/{name}")


@dataclass(frozen=True, slots=True)
class DemoSeed:
    """Immutable collection of synthetic candidates and parsed documents."""

    papers: tuple[PaperCandidate, ...]
    documents: tuple[Document, ...]


_PAPER_DATA = (
    {
        "key": "paper-a",
        "title": "YOLO-SLAM: Real-Time Dynamic Object Filtering for Visual SLAM",
        "authors": ("Lin Chen", "Mei Zhang"),
        "year": 2024,
        "abstract": (
            "A synthetic demonstration study combining YOLO detections with "
            "feature-level dynamic-object filtering in visual SLAM."
        ),
        "method": (
            "The method removes feature points inside temporally consistent YOLO "
            "dynamic-object masks before camera pose estimation."
        ),
        "experiment": (
            "On the synthetic Demo-SLAM benchmark, trajectory RMSE improves from "
            "0.18 m to 0.11 m compared with an unfiltered baseline."
        ),
        "method_name": "Temporal Mask Feature Filtering",
        "dataset": "Demo-SLAM",
        "metric": "trajectory_rmse",
        "metric_value": "0.11 m; baseline=0.18 m",
        "baseline": "Unfiltered visual SLAM",
    },
    {
        "key": "paper-b",
        "title": "Semantic YOLO Constraints for Robust Visual-Inertial SLAM",
        "authors": ("Alex Wu", "Sara Patel"),
        "year": 2025,
        "abstract": (
            "A synthetic demonstration study using YOLO semantic labels as robust "
            "constraints in visual-inertial optimization."
        ),
        "method": (
            "Semantic confidence from YOLO adaptively weights visual residuals in "
            "the visual-inertial optimization backend."
        ),
        "experiment": (
            "The synthetic indoor sequence reports 27 percent lower absolute "
            "trajectory error than the geometry-only baseline."
        ),
        "method_name": "Semantic Residual Reweighting",
        "dataset": "Demo-Indoor-VIO",
        "metric": "absolute_trajectory_error",
        "metric_value": "27% lower",
        "baseline": "Geometry-only visual-inertial SLAM",
    },
    {
        "key": "paper-c",
        "title": "Object-Aware Semantic Mapping with YOLO and RGB-D SLAM",
        "authors": ("Nora Kim", "Tao Li"),
        "year": 2026,
        "abstract": (
            "A synthetic demonstration study that associates YOLO observations "
            "across RGB-D frames to construct an object-level semantic map."
        ),
        "method": (
            "The system fuses tracked YOLO instances with RGB-D landmarks to build "
            "a persistent object-level semantic map."
        ),
        "experiment": (
            "In the synthetic office benchmark, object association precision reaches "
            "91 percent while maintaining real-time processing."
        ),
        "method_name": "Persistent Object Association",
        "dataset": "Demo-RGBD-Office",
        "metric": "object_association_precision",
        "metric_value": "91%",
        "baseline": "Frame-local detections",
    },
)


def create_demo_seed() -> DemoSeed:
    """Build fresh deep-copy-safe seed objects with stable identifiers."""

    papers: list[PaperCandidate] = []
    documents: list[Document] = []
    for index, item in enumerate(_PAPER_DATA, start=1):
        paper_id = _demo_uuid(item["key"])
        title = str(item["title"])
        paper = PaperCandidate(
            id=paper_id,
            title=title,
            normalized_title=title.casefold(),
            abstract=str(item["abstract"]),
            authors=[
                Author(
                    full_name=name,
                    normalized_name=name.casefold(),
                    affiliations=["PaperPilot Demo Lab"],
                )
                for name in item["authors"]
            ],
            publication_year=int(item["year"]),
            venue="PaperPilot Offline Demo Proceedings",
            arxiv_id=f"demo.{index:04d}",
            sources=[PaperSource.ARXIV],
            landing_page_url=f"https://example.invalid/demo/{item['key']}",
            pdf_url=f"https://example.invalid/demo/{item['key']}.pdf",
            citation_count=index * 7,
            full_text_status=FullTextStatus.AVAILABLE,
            relevance_score=1.0 - ((index - 1) * 0.05),
            selection_reason="Deterministic offline demonstration candidate.",
        )
        method_text = str(item["method"])
        experiment_text = str(item["experiment"])
        page_text = (
            f"1 Introduction\n{paper.abstract}\n\n"
            f"2 Method\n{method_text}\n\n"
            f"3 Experiments\n{experiment_text}\n"
        )
        documents.append(
            Document(
                id=_demo_uuid(f"{item['key']}-document"),
                paper_id=paper_id,
                title=title,
                source_path=f"demo://{item['key']}.pdf",
                pages=[Page(page_number=1, text=page_text)],
                sections=[
                    Section(
                        title="Introduction",
                        page_start=1,
                        page_end=1,
                        text=str(item["abstract"]),
                    ),
                    Section(
                        title="Method",
                        page_start=1,
                        page_end=1,
                        text=method_text,
                    ),
                    Section(
                        title="Experiments",
                        page_start=1,
                        page_end=1,
                        text=experiment_text,
                    ),
                ],
                metadata={
                    "demo": True,
                    "method_name": item["method_name"],
                    "method_quote": method_text,
                    "experiment_quote": experiment_text,
                    "dataset": item["dataset"],
                    "metric": item["metric"],
                    "metric_value": item["metric_value"],
                    "baseline": item["baseline"],
                },
            )
        )
        papers.append(paper)
    return DemoSeed(papers=tuple(papers), documents=tuple(documents))


class DemoDocumentIngestionPipeline:
    """Offline document source satisfying the existing ingestion-node contract."""

    def __init__(self, seed: DemoSeed) -> None:
        self._documents = {document.paper_id: document for document in seed.documents}

    def ingest(self, papers: list[PaperCandidate]) -> DocumentIngestionResult:
        """Return seeded parsed documents without network or filesystem access."""

        items: list[PaperIngestionItem] = []
        documents: list[Document] = []
        for paper in papers:
            document = self._documents.get(paper.id)
            if document is None:
                items.append(
                    PaperIngestionItem(
                        paper_id=paper.id,
                        title=paper.title,
                        status=IngestionStatus.FAILED,
                        error_stage="demo_seed",
                        error_type="DemoDocumentNotFoundError",
                        error_message="demo document is unavailable",
                    )
                )
                continue
            copied = document.model_copy(deep=True)
            documents.append(copied)
            items.append(
                PaperIngestionItem(
                    paper_id=paper.id,
                    title=paper.title,
                    status=IngestionStatus.PARSED,
                    document=copied,
                    downloaded_file_path=copied.source_path,
                    content_hash=_demo_uuid(f"{paper.id}-content").hex * 2,
                    size_bytes=len(copied.pages[0].text.encode("utf-8")),
                    page_count=len(copied.pages),
                    warnings=["Synthetic offline demo document."],
                )
            )
        failed = sum(item.status is IngestionStatus.FAILED for item in items)
        return DocumentIngestionResult(
            items=items,
            documents=documents,
            total_requested=len(items),
            total_eligible=len(items),
            total_downloaded=len(documents),
            total_parsed=len(documents),
            total_skipped=0,
            total_failed=failed,
            warnings=["Demo mode uses synthetic documents and performs no downloads."],
        )
