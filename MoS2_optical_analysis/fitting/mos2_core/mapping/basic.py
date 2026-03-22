"""Default map analysis implementations."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Sequence

from ..core.interfaces import MapAnalysisStage
from ..core.types import MapAnalysisResult, ParameterSet, PipelineContext


class SimpleMapAnalysis(MapAnalysisStage):
    """Aggregate parameters into map-level summaries."""

    def run(
        self,
        parameters: Sequence[ParameterSet],
        context: PipelineContext,
    ) -> list[MapAnalysisResult]:
        grouped: dict[str, list[ParameterSet]] = defaultdict(list)
        for item in parameters:
            map_id = str(item.metadata.get("map_id", "default_map"))
            grouped[map_id].append(item)

        results: list[MapAnalysisResult] = []
        for map_id, items in grouped.items():
            peak_positions = [
                float(p.parameters["peak_position"])
                for p in items
                if "peak_position" in p.parameters
            ]
            peak_amplitudes = [
                float(p.parameters["peak_amplitude"])
                for p in items
                if "peak_amplitude" in p.parameters
            ]
            e2g_positions = [
                float(p.parameters["e2g_position"])
                for p in items
                if "e2g_position" in p.parameters
            ]
            a1g_positions = [
                float(p.parameters["a1g_position"])
                for p in items
                if "a1g_position" in p.parameters
            ]
            deltas = [
                float(p.parameters["delta_e2g_a1g"])
                for p in items
                if "delta_e2g_a1g" in p.parameters
            ]

            summary = {
                "n_spectra": len(items),
                "mean_peak_position": mean(peak_positions) if peak_positions else None,
                "mean_peak_amplitude": mean(peak_amplitudes) if peak_amplitudes else None,
                "mean_e2g_position": mean(e2g_positions) if e2g_positions else None,
                "mean_a1g_position": mean(a1g_positions) if a1g_positions else None,
                "mean_delta_e2g_a1g": mean(deltas) if deltas else None,
            }
            results.append(MapAnalysisResult(map_id=map_id, summary=summary, layers={}))

        context.state["map_count"] = len(results)
        return results
