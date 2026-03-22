"""Pipeline entrypoint that orchestrates all analysis stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

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
from .types import PipelineContext, PipelineResult, SpectrumRecord


@dataclass(slots=True)
class PipelineStages:
    """Container of stage implementations injected into the pipeline."""

    qc: QCStage
    preprocess: PreprocessingStage
    baseline_ensemble: BaselineEnsembleStage
    model_ensemble_fitting: ModelEnsembleFittingStage
    model_selection: ModelSelectionStage
    post_selection_qc: PostSelectionQCStage
    confidence_scoring: ConfidenceScoringStage
    review_queue: ReviewQueueStage
    manual_review: ManualReviewStage
    parameter_extraction: ParameterExtractionStage
    map_analysis: MapAnalysisStage
    report_generation: ReportGenerationStage


class MoS2Pipeline:
    """Run Raman/PL pipeline from raw spectra to final reports."""

    def __init__(self, stages: PipelineStages) -> None:
        self.stages = stages

    def run(
        self,
        raw_spectra: Sequence[SpectrumRecord],
        context: PipelineContext | None = None,
    ) -> PipelineResult:
        ctx = context or PipelineContext()

        qc_passed, qc_results = self.stages.qc.run(raw_spectra, ctx)
        preprocessed = self.stages.preprocess.run(qc_passed, ctx)
        baselines = self.stages.baseline_ensemble.run(preprocessed, ctx)
        fit_ensemble = self.stages.model_ensemble_fitting.run(preprocessed, baselines, ctx)
        selected = self.stages.model_selection.run(fit_ensemble, ctx)
        selected_qc = self.stages.post_selection_qc.run(selected, ctx)
        confidence = self.stages.confidence_scoring.run(selected_qc, ctx)
        flagged = self.stages.review_queue.run(selected_qc, confidence, ctx)
        accepted, decisions = self.stages.manual_review.run(selected_qc, baselines, flagged, ctx)
        parameters = self.stages.parameter_extraction.run(accepted, ctx)
        maps = self.stages.map_analysis.run(parameters, ctx)

        # Reports depend on PipelineResult, so build once without reports first.
        partial_result = PipelineResult(
            qc=qc_results,
            flagged=flagged,
            decisions=decisions,
            accepted=accepted,
            parameters=parameters,
            maps=maps,
            reports=[],
        )
        reports = self.stages.report_generation.run(partial_result, ctx)

        return PipelineResult(
            qc=qc_results,
            flagged=flagged,
            decisions=decisions,
            accepted=accepted,
            parameters=parameters,
            maps=maps,
            reports=reports,
        )


def run_pipeline(
    raw_spectra: Sequence[SpectrumRecord],
    stages: PipelineStages,
    context: PipelineContext | None = None,
) -> PipelineResult:
    """Convenience function for one-off pipeline runs."""

    return MoS2Pipeline(stages=stages).run(raw_spectra=raw_spectra, context=context)
