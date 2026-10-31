"""Core pipeline APIs."""

from .interfaces import (
    BaselineEnsembleStage,
    ConfidenceScoringStage,
    ManualReviewStage,
    MapAnalysisStage,
    ModelEnsembleFittingStage,
    ModelSelectionStage,
    ParameterExtractionStage,
    PostSelectionQCStage,
    PreprocessingStage,
    QCStage,
    ReportGenerationStage,
    ReviewQueueStage,
)
from .pipeline import MoS2Pipeline, PipelineStages, run_pipeline
from .types import (
    AcceptedResult,
    BaselineCandidate,
    BaselineResult,
    ConfidenceResult,
    FitCandidate,
    FitEnsembleResult,
    MapAnalysisResult,
    ParameterSet,
    PipelineContext,
    PipelineResult,
    PreprocessedSpectrum,
    QCSummary,
    ReportArtifact,
    ReviewDecision,
    ReviewItem,
    SelectionResult,
    SpectrumRecord,
)

__all__ = [
    "AcceptedResult",
    "BaselineCandidate",
    "BaselineEnsembleStage",
    "BaselineResult",
    "build_default_context",
    "build_default_stages",
    "ConfidenceResult",
    "ConfidenceScoringStage",
    "FitCandidate",
    "FitEnsembleResult",
    "ManualReviewStage",
    "MapAnalysisResult",
    "MapAnalysisStage",
    "ModelEnsembleFittingStage",
    "ModelSelectionStage",
    "MoS2Pipeline",
    "ParameterExtractionStage",
    "ParameterSet",
    "PipelineContext",
    "PipelineResult",
    "PipelineStages",
    "PostSelectionQCStage",
    "PreprocessedSpectrum",
    "PreprocessingStage",
    "QCSummary",
    "QCStage",
    "ReportArtifact",
    "ReportGenerationStage",
    "ReviewDecision",
    "ReviewItem",
    "ReviewQueueStage",
    "SelectionResult",
    "SpectrumRecord",
    "run_pipeline",
]


def __getattr__(name: str):
    # Lazy: default_stages imports the stage packages (fitting, analysis, ...), which import
    # core.interfaces/core.types. Importing it eagerly here made `import fitting.mos2_core.fitting.raman_lmfit`
    # fail with a circular import (e.g. in spawned fit worker processes).
    if name in {"build_default_context", "build_default_stages"}:
        from . import default_stages

        return getattr(default_stages, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
