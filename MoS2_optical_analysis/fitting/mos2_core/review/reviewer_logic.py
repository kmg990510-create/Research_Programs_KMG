"""Rules for confidence scoring and review eligibility."""

from __future__ import annotations

from typing import Mapping, Sequence

from ..core.interfaces import ManualReviewStage
from ..core.types import (
    AcceptedResult,
    BaselineResult,
    PipelineContext,
    ReviewDecision,
    ReviewItem,
    SelectionResult,
)


class AutoApproveManualReview(ManualReviewStage):
    """
    Manual review stage stub for development.

    Flagged spectra are marked as reviewed and approved by a synthetic reviewer.
    """

    def run(
        self,
        selections: Mapping[str, SelectionResult],
        baselines: Mapping[str, BaselineResult],
        review_items: Sequence[ReviewItem],
        context: PipelineContext,
    ) -> tuple[list[AcceptedResult], list[ReviewDecision]]:
        review_by_id = {item.spectrum_id: item for item in review_items}
        accepted: list[AcceptedResult] = []
        decisions: list[ReviewDecision] = []
        accepted_invalid_count = 0

        for spectrum_id, selection in selections.items():
            fit_status = str(selection.selected.params.get("fit_status", "valid")).strip().lower()
            if fit_status == "invalid":
                accepted_invalid_count += 1

            baseline = baselines[spectrum_id].selected
            reviewed = spectrum_id in review_by_id
            decision: ReviewDecision | None = None

            if reviewed:
                reason = review_by_id[spectrum_id].reason
                decision = ReviewDecision(
                    spectrum_id=spectrum_id,
                    decision="approved_auto_stub",
                    reviewer_id="system",
                    notes=f"Automatically approved during stub review. reason={reason}",
                )
                decisions.append(decision)

            accepted.append(
                AcceptedResult(
                    spectrum_id=spectrum_id,
                    fit=selection.selected,
                    baseline=baseline,
                    reviewed=reviewed,
                    review_decision=decision,
                )
            )

        context.state["accepted_count"] = len(accepted)
        context.state["reviewed_count"] = len(decisions)
        context.state["accepted_invalid_count"] = accepted_invalid_count
        return accepted, decisions
