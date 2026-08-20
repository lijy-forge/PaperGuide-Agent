"""Public deterministic comparison contracts and builder."""

from .analysis_data import (
    ComparisonCell,
    ComparisonColumn,
    ComparisonDataBuilder,
    ComparisonMatrixData,
    ComparisonRow,
    ComparabilityAssessment,
    ComparabilityLevel,
    CrossPaperComparisonFacts,
    GroundingStatus,
    SurveyAnalysisData,
    SurveyAnalysisDataBuilder,
    TaxonomyEvidenceCoverage,
)

__all__ = [name for name in globals() if not name.startswith("_")]
