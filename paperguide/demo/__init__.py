"""Offline demonstration dependencies for the existing PaperGuide workflow."""

from .fake_provider import DemoProvider, create_demo_application
from .fake_reader import FakeReader
from .fake_retriever import FakeRetriever
from .fake_verifier import FakeVerifier
from .seed import DEMO_QUESTION, DemoDocumentIngestionPipeline, create_demo_seed

__all__ = [
    "DEMO_QUESTION",
    "DemoDocumentIngestionPipeline",
    "DemoProvider",
    "FakeReader",
    "FakeRetriever",
    "FakeVerifier",
    "create_demo_application",
    "create_demo_seed",
]
