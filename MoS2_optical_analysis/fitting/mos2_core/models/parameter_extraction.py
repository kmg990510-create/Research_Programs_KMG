"""Default parameter extraction implementations."""

from __future__ import annotations

from typing import Sequence

from ..core.interfaces import ParameterExtractionStage
from ..core.types import AcceptedResult, ParameterSet, PipelineContext


class BasicParameterExtraction(ParameterExtractionStage):
    """Extract a stable parameter dictionary from accepted fit results."""

    def run(
        self,
        accepted: Sequence[AcceptedResult],
        context: PipelineContext,
    ) -> list[ParameterSet]:
        metadata_index = context.state.get("spectrum_metadata", {})
        output: list[ParameterSet] = []
        invalid_excluded_count = 0
        for item in accepted:
            fit_status = str(item.fit.params.get("fit_status", "valid")).strip().lower()
            if fit_status == "invalid":
                invalid_excluded_count += 1
                continue

            params = dict(item.fit.params)
            params["baseline_score"] = float(item.baseline.score)
            spectrum_meta = metadata_index.get(item.spectrum_id, {})
            map_id = spectrum_meta.get("map_id", "default_map")

            output.append(
                ParameterSet(
                    spectrum_id=item.spectrum_id,
                    parameters=params,
                    metadata={
                        "reviewed": item.reviewed,
                        "decision": item.review_decision.decision
                        if item.review_decision
                        else "auto",
                        "map_id": map_id,
                        "map_x": spectrum_meta.get("map_x"),
                        "map_y": spectrum_meta.get("map_y"),
                    },
                )
            )

        context.state["parameter_count"] = len(output)
        context.state["parameter_invalid_excluded_count"] = invalid_excluded_count
        return output
