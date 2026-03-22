"""Default baseline ensemble implementations."""

from __future__ import annotations

from typing import Mapping, Sequence

from ..core.interfaces import BaselineEnsembleStage
from ..core.types import BaselineCandidate, BaselineResult, PipelineContext, PreprocessedSpectrum


class ZeroBaselineEnsemble(BaselineEnsembleStage):
    """
    Baseline ensemble stub that returns a zero baseline.

    Intended for end-to-end wiring verification before real methods are plugged in.
    """

    def run(
        self,
        spectra: Sequence[PreprocessedSpectrum],
        context: PipelineContext,
    ) -> Mapping[str, BaselineResult]:
        baseline_cfg = context.config.get("baseline", {})
        method_name = (
            str(baseline_cfg.get("default_method", "zero_baseline"))
            if isinstance(baseline_cfg, dict)
            else "zero_baseline"
        )
        score = (
            float(baseline_cfg.get("default_score", 1.0))
            if isinstance(baseline_cfg, dict)
            else 1.0
        )

        results: dict[str, BaselineResult] = {}
        for spectrum in spectra:
            baseline = [0.0] * len(spectrum.y)
            candidate = BaselineCandidate(
                method_name=method_name,
                baseline_y=baseline,
                score=score,
                diagnostics={"note": "stub"},
            )
            results[spectrum.spectrum_id] = BaselineResult(selected=candidate, candidates=[candidate])

        context.state["baseline_count"] = len(results)
        return results
