"""Review queue generation and retrieval logic."""

from __future__ import annotations

import time
from typing import Mapping

from ..core.interfaces import ReviewQueueStage
from ..core.types import ConfidenceResult, PipelineContext, ReviewItem, SelectionResult


class ThresholdReviewQueue(ReviewQueueStage):
    """Queue spectra that are marked as requiring review."""

    def run(
        self,
        selections: Mapping[str, SelectionResult],
        confidence: Mapping[str, ConfidenceResult],
        context: PipelineContext,
    ) -> list[ReviewItem]:
        queue: list[ReviewItem] = []
        selected_valid_total = sum(
            1
            for selection in selections.values()
            if str(selection.selected.params.get("fit_status", "valid")).strip().lower() == "valid"
        )
        flagged_valid_count = 0
        progress_enabled = bool(context.state.get("progress_enabled", False))
        try:
            progress_every = max(int(float(context.state.get("progress_every", 5))), 1)
        except (TypeError, ValueError):
            progress_every = 5
        total = len(selections)
        t0 = time.perf_counter()
        if progress_enabled and total > 0:
            print(f"[review] start: {total} spectra", flush=True)

        for index, spectrum_id in enumerate(selections, start=1):
            conf = confidence.get(spectrum_id)
            if not conf or not conf.requires_review:
                if progress_enabled and (index % progress_every == 0 or index == total):
                    elapsed = time.perf_counter() - t0
                    print(
                        "[review] "
                        f"{index}/{total} | flagged_valid={flagged_valid_count}/{selected_valid_total} "
                        f"| queue={len(queue)} | elapsed={elapsed:.1f}s",
                        flush=True,
                    )
                continue
            reason = ", ".join(conf.reasons) if conf.reasons else "requires_manual_review"
            fit_status = str(
                selections[spectrum_id].selected.params.get("fit_status", "valid")
            ).strip().lower()
            if fit_status == "valid":
                flagged_valid_count += 1
            queue.append(
                ReviewItem(
                    spectrum_id=spectrum_id,
                    reason=reason,
                    confidence_score=float(conf.score),
                    metadata={},
                )
            )
            if progress_enabled and (index % progress_every == 0 or index == total):
                elapsed = time.perf_counter() - t0
                print(
                    "[review] "
                    f"{index}/{total} | flagged_valid={flagged_valid_count}/{selected_valid_total} "
                    f"| queue={len(queue)} | elapsed={elapsed:.1f}s",
                    flush=True,
                )

        context.state["flagged_count"] = len(queue)
        context.state["flagged_valid_count"] = flagged_valid_count
        context.state["selected_valid_total"] = selected_valid_total
        return queue
