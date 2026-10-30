"""Default confidence scoring implementations."""

from __future__ import annotations

from typing import Mapping

from ..core.interfaces import ConfidenceScoringStage
from ..core.types import ConfidenceResult, PipelineContext, SelectionResult


class SimpleConfidenceScorer(ConfidenceScoringStage):
    """
    Confidence scorer using simple metric heuristics.

    Confidence score is normalized to [0, 1], and low confidence is flagged
    for manual review.
    """

    def __init__(self, threshold: float = 0.8) -> None:
        self.threshold = threshold

    def run(
        self,
        selections: Mapping[str, SelectionResult],
        context: PipelineContext,
    ) -> Mapping[str, ConfidenceResult]:
        review_cfg = context.config.get("review", {})
        threshold = float(review_cfg.get("confidence_threshold", self.threshold))
        high_rmse_threshold = float(review_cfg.get("high_rmse_threshold", 0.2))

        output: dict[str, ConfidenceResult] = {}
        for spectrum_id, selection in selections.items():
            rmse = float(selection.selected.metrics.get("rmse", 0.5))
            amp = abs(float(selection.selected.params.get("peak_amplitude", 1.0)))
            fit_status = str(selection.selected.params.get("fit_status", "valid")).strip().lower()

            denom = max(amp, 1e-6)
            raw = 1.0 - (rmse / denom)
            score = max(0.0, min(1.0, raw))

            reasons: list[str] = []
            requires_review = score < threshold
            if fit_status == "invalid":
                score = 0.0
                requires_review = True
                reasons.append("invalid_fit_status")
            elif fit_status == "attention":
                requires_review = True
                reasons.append("attention_fit_status")

            if score < threshold:
                reasons.append("low_confidence_score")
            if rmse > high_rmse_threshold:
                reasons.append("high_rmse")

            output[spectrum_id] = ConfidenceResult(
                score=score,
                requires_review=requires_review,
                reasons=reasons,
            )

        context.state["confidence_threshold"] = threshold
        context.state["confidence_count"] = len(output)
        return output
