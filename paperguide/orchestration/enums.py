"""String enums used by the PaperGuide orchestration state contract."""

from enum import Enum


class ResearchStep(str, Enum):
    """Current lifecycle stage of a research run."""

    INITIALIZED = "initialized"
    PLANNING = "planning"
    RETRIEVAL = "retrieval"
    INGESTION = "ingestion"
    READING = "reading"
    VERIFICATION = "verification"
    QUALITY_GATE = "quality_gate"
    COMPLETED = "completed"
    FAILED = "failed"


class NextAction(str, Enum):
    """Next routing action selected for a research run."""

    RETRIEVE = "retrieve"
    INGEST = "ingest"
    READ = "read"
    VERIFY = "verify"
    EVALUATE_QUALITY = "evaluate_quality"
    RETRY_RETRIEVAL = "retry_retrieval"
    RETRY_INGESTION = "retry_ingestion"
    RETRY_READING = "retry_reading"
    RETRY_VERIFICATION = "retry_verification"
    HUMAN_REVIEW = "human_review"
    COMPLETE = "complete"
    COMPLETE_DEGRADED = "complete_degraded"
    ABORT = "abort"


class PaperStageStatus(str, Enum):
    """Per-paper progress through the research workflow."""

    PENDING = "pending"
    RETRIEVING = "retrieving"
    RETRIEVED = "retrieved"
    INGESTING = "ingesting"
    INGESTED = "ingested"
    READING = "reading"
    ANALYZED = "analyzed"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    FAILED = "failed"
    SKIPPED = "skipped"
