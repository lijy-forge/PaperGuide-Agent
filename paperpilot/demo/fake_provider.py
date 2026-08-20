"""Offline structured provider and demo-specific dependency composition."""

import json
import re
from collections.abc import Sequence
from typing import TypeVar

from pydantic import BaseModel

from paperpilot.adapters import RetrieverProtocol
from paperpilot.application import TaskStoreProtocol
from paperpilot.bootstrap import (
    ApplicationContainer,
    BootstrapConfig,
    create_application,
)
from paperpilot.orchestration import create_research_graph
from paperpilot.orchestration.nodes import IngestionNode, ReaderNode, VerifierNode
from paperpilot.reporting import ResearchReport
from paperpilot.relevance import DeterministicQueryExpansionService, ResearchIntent, TimeRange

from .fake_reader import FakeReader
from .fake_retriever import FakeRetriever
from .fake_verifier import FakeVerifier
from .seed import DemoDocumentIngestionPipeline, create_demo_seed

ModelT = TypeVar("ModelT", bound=BaseModel)


class DemoProvider:
    """Generate a deterministic report schema without credentials or network I/O."""

    model_name = "paperpilot-offline-demo"

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ModelT],
    ) -> ModelT:
        """Return the supported structured response from verified context only."""

        del system_prompt
        # Demo mode follows the same production Survey path.  It supports the
        # bounded Survey stage contract as a deterministic local stand-in, not
        # as a second report pipeline.
        from paperpilot.reporting.synthesis import SurveyStageDraft

        if response_model is SurveyStageDraft:
            match = re.search(r"stage ([A-D])", user_prompt)
            if match is None:
                raise ValueError("unsupported demo survey prompt")
            return response_model.model_validate(
                {
                    "stage": match.group(1),
                    "title": "YOLO与视觉SLAM融合研究进展（离线演示）",
                    "paragraphs": [
                        {
                            "text": "本离线演示基于合成论文和合成证据，仅用于展示证据驱动调研工作流。"
                        }
                    ],
                    "warnings": [
                        "Offline demo uses synthetic papers and must not be cited as real research."
                    ],
                }
            )
        if response_model is not ResearchReport:
            raise ValueError("unsupported demo structured response")
        question, evidence = self._parse_report_prompt(user_prompt)
        if not evidence:
            raise ValueError("verified demo evidence is required")
        evidence_ids = [item["evidence_id"] for item in evidence]
        report = {
            "question": question,
            "title": "YOLO与视觉SLAM融合研究进展（离线演示）",
            "summary": (
                "模拟证据显示，YOLO可通过动态特征过滤、语义残差加权和对象级地图构建"
                "三类路径与视觉SLAM结合。本报告仅用于离线产品演示。"
            ),
            "sections": [
                {
                    "title": "方法与实验观察",
                    "claims": [
                        {
                            "text": item["claim"],
                            "evidence_ids": [item["evidence_id"]],
                        }
                        for item in evidence
                    ],
                    "evidence_ids": evidence_ids,
                }
            ],
            "citations": [
                {
                    "paper_id": item["paper_id"],
                    "evidence_id": item["evidence_id"],
                    "quote": item["quote"],
                    "locator": item["locator"],
                }
                for item in evidence
            ],
            "evidence_ids": evidence_ids,
            "warnings": [
                "Offline demo uses synthetic papers and must not be cited as real research."
            ],
        }
        return response_model.model_validate(report)

    @staticmethod
    def _parse_report_prompt(user_prompt: str) -> tuple[str, list[dict[str, object]]]:
        question_marker = "Research question:\n"
        context_marker = "\n\nVerified report context (JSON Lines):\n"
        if question_marker not in user_prompt or context_marker not in user_prompt:
            raise ValueError("unsupported demo report prompt")
        question_and_context = user_prompt.split(question_marker, 1)[1]
        preamble, context = question_and_context.split(context_marker, 1)
        question = preamble.split("\n\n", 1)[0]
        rows = [json.loads(line) for line in context.splitlines() if line.strip()]
        evidence = [
            {key: value for key, value in row.items() if key != "record_type"}
            for row in rows
            if row.get("record_type") == "verified_evidence"
        ]
        return question.strip(), evidence


class _DemoIntentPlanner:
    """Map the fixed synthetic topic to generic concepts without an LLM."""

    def plan(self, question: str) -> ResearchIntent:
        return ResearchIntent(
            research_question=question.strip(),
            required_concepts=["YOLO", "SLAM"],
            relation_requirements=["YOLO dynamic object masks"],
            domain="visual SLAM",
            time_range=TimeRange(start_year=2024, end_year=2026),
        )


def create_demo_application(
    config: BootstrapConfig,
    *,
    task_store: TaskStoreProtocol | None = None,
    retrievers: Sequence[RetrieverProtocol] | None = None,
) -> ApplicationContainer:
    """Compose the existing application with offline external dependencies."""

    seed = create_demo_seed()
    fake_reader = FakeReader()
    fake_verifier = FakeVerifier()
    demo_ingestion = DemoDocumentIngestionPipeline(seed)

    def demo_graph_factory(
        planner_node,
        retriever_node,
        ingestion_node,
        reader_node,
        verifier_node,
        quality_gate_node,
    ):
        del ingestion_node, reader_node
        return create_research_graph(
            planner_node,
            retriever_node,
            IngestionNode(demo_ingestion),
            ReaderNode(fake_reader),
            VerifierNode(
                fake_verifier,
                final_relevance_service=verifier_node.final_relevance_service,
                evidence_linking_service=verifier_node.evidence_linking_service,
            ),
            quality_gate_node,
        )

    return create_application(
        config,
        structured_llm=DemoProvider(),
        retrievers=(
            list(retrievers) if retrievers is not None else [FakeRetriever(seed)]
        ),
        task_store=task_store,
        graph_factory=demo_graph_factory,
        intent_planner=_DemoIntentPlanner(),
        query_expander=DeterministicQueryExpansionService(),
    )
