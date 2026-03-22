"""Factory helpers to build default pipeline stage implementations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ..analysis import MahalanobisPostSelectionQC, RamanFitReportGenerator, SimpleConfidenceScorer
from ..baseline import ZeroBaselineEnsemble
from ..fitting import EnsembleMetricModelSelection, LmfitRamanModelEnsembleFitting
from ..io import load_pipeline_config
from ..mapping import SimpleMapAnalysis
from ..models import BasicParameterExtraction
from ..preprocess import IdentityPreprocessing, PassThroughQC
from ..review.queue import ThresholdReviewQueue
from ..review.reviewer_logic import AutoApproveManualReview
from .pipeline import PipelineStages
from .types import PipelineContext


def _pl_enabled_from_config(config: Mapping[str, Any] | None) -> bool:
    if config is None:
        return True
    pl_section = config.get("pl", {})
    if not isinstance(pl_section, Mapping):
        return False
    models = pl_section.get("models", [])
    if not isinstance(models, list):
        return False
    return any(str(item).strip() for item in models)


def build_default_stages(config: Mapping[str, Any] | None = None) -> PipelineStages:
    """Build a runnable default pipeline using stub implementations."""

    pl_enabled = _pl_enabled_from_config(config)
    return PipelineStages(
        qc=PassThroughQC(),
        preprocess=IdentityPreprocessing(),
        baseline_ensemble=ZeroBaselineEnsemble(),
        model_ensemble_fitting=LmfitRamanModelEnsembleFitting(enable_pl=pl_enabled),
        model_selection=EnsembleMetricModelSelection(),
        post_selection_qc=MahalanobisPostSelectionQC(),
        confidence_scoring=SimpleConfidenceScorer(),
        review_queue=ThresholdReviewQueue(),
        manual_review=AutoApproveManualReview(),
        parameter_extraction=BasicParameterExtraction(),
        map_analysis=SimpleMapAnalysis(),
        report_generation=RamanFitReportGenerator(),
    )


def build_default_context(
    run_id: str = "dev_run",
    artifact_dir: Path | None = None,
    config_dir: Path | None = None,
    config: Mapping[str, Any] | None = None,
) -> PipelineContext:
    """Build default runtime context for local development."""

    resolved_artifact_dir = artifact_dir or Path.cwd()
    if config is not None:
        resolved_config = dict(config)
    else:
        resolved_config = load_pipeline_config(config_dir or (resolved_artifact_dir / "config"))

    return PipelineContext(
        run_id=run_id,
        artifact_dir=resolved_artifact_dir,
        config=resolved_config,
    )
