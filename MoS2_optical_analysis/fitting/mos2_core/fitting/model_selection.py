"""Model-selection stages for fit ensemble outputs."""

from __future__ import annotations

import time
from typing import Mapping, Sequence

from ..core.interfaces import ModelSelectionStage
from ..core.types import FitCandidate, FitEnsembleResult, PipelineContext, SelectionResult
from ..io import config_access as cfgx

_METRICS = {"aic", "bic", "rmse", "hybrid"}


class EnsembleMetricModelSelection(ModelSelectionStage):
    """
    Select best model from ensemble candidates.

    Supported selection metrics (all minimized):
    - aic
    - bic
    - rmse
    - hybrid: weighted normalized combination of (aic, bic, rmse)

    Metric and hybrid weights come from `{modality}.selection_metric` / `{modality}.hybrid_weights`.
    """

    @staticmethod
    def _safe_metric(candidate: FitCandidate, metric_name: str) -> float:
        raw = candidate.metrics.get(metric_name, float("inf"))
        try:
            return float(raw)
        except (TypeError, ValueError):
            return float("inf")

    @staticmethod
    def _is_selectable(candidate: FitCandidate) -> bool:
        fit_status = str(candidate.params.get("fit_status", "valid")).strip().lower()
        if fit_status == "invalid":
            return False
        raw_valid = candidate.metrics.get("is_valid_candidate", 1.0)
        try:
            return float(raw_valid) > 0.5
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _metric_for_modality(modality: str, context: PipelineContext) -> str:
        metric = cfgx.text(cfgx.section(context.config, modality, ""), "selection_metric", modality).lower()
        if metric not in _METRICS:
            raise cfgx.ConfigKeyError(
                f"config.yaml: '{modality}.selection_metric' must be one of {sorted(_METRICS)} (got {metric!r})"
            )
        return metric

    @staticmethod
    def _normalize(values: Sequence[float]) -> list[float]:
        if not values:
            return []
        vmin = min(values)
        vmax = max(values)
        if vmax <= vmin:
            return [0.0 for _ in values]
        return [(v - vmin) / (vmax - vmin) for v in values]

    @staticmethod
    def _hybrid_weights(modality: str, context: PipelineContext) -> tuple[float, float, float]:
        weights = cfgx.section(cfgx.section(context.config, modality, ""), "hybrid_weights", modality)
        path = f"{modality}.hybrid_weights"
        return (
            cfgx.number(weights, "aic", path),
            cfgx.number(weights, "bic", path),
            cfgx.number(weights, "rmse", path),
        )

    def _hybrid_score(
        self,
        candidate: FitCandidate,
        normalized_cache: dict[str, dict[str, float]],
        weights: tuple[float, float, float],
    ) -> float:
        name = candidate.model_name
        aic = normalized_cache["aic"].get(name, 1.0)
        bic = normalized_cache["bic"].get(name, 1.0)
        rmse = normalized_cache["rmse"].get(name, 1.0)
        w_aic, w_bic, w_rmse = weights
        return w_aic * aic + w_bic * bic + w_rmse * rmse

    def run(
        self,
        fit_results: Mapping[str, FitEnsembleResult],
        context: PipelineContext,
    ) -> Mapping[str, SelectionResult]:
        selected: dict[str, SelectionResult] = {}
        metric_usage: dict[str, int] = {"aic": 0, "bic": 0, "rmse": 0, "hybrid": 0}
        ranking_table: dict[str, list[dict[str, float | str]]] = {}
        selected_status_counts: dict[str, int] = {"valid": 0, "attention": 0, "invalid": 0}
        progress_enabled = bool(context.state.get("progress_enabled", False))
        try:
            progress_every = max(int(float(context.state.get("progress_every", 5))), 1)
        except (TypeError, ValueError):
            progress_every = 5
        total = len(fit_results)
        t0 = time.perf_counter()
        if progress_enabled and total > 0:
            print(f"[select] start: {total} spectra", flush=True)

        for index, (spectrum_id, result) in enumerate(fit_results.items(), start=1):
            if not result.candidates:
                continue

            metric_name = self._metric_for_modality(result.modality, context)
            # Weights are validated for every run so a broken value cannot hide until `hybrid` is chosen.
            weights = self._hybrid_weights(result.modality, context)
            metric_usage[metric_name] = metric_usage.get(metric_name, 0) + 1
            selectable_candidates = [c for c in result.candidates if self._is_selectable(c)]
            ranked_pool = selectable_candidates if selectable_candidates else list(result.candidates)

            if metric_name == "hybrid":
                aic_values = [self._safe_metric(c, "aic") for c in ranked_pool]
                bic_values = [self._safe_metric(c, "bic") for c in ranked_pool]
                rmse_values = [self._safe_metric(c, "rmse") for c in ranked_pool]

                aic_norm = self._normalize(aic_values)
                bic_norm = self._normalize(bic_values)
                rmse_norm = self._normalize(rmse_values)
                cache = {
                    "aic": {c.model_name: aic_norm[i] for i, c in enumerate(ranked_pool)},
                    "bic": {c.model_name: bic_norm[i] for i, c in enumerate(ranked_pool)},
                    "rmse": {c.model_name: rmse_norm[i] for i, c in enumerate(ranked_pool)},
                }

                ranked = sorted(
                    ranked_pool,
                    key=lambda c: self._hybrid_score(c, cache, weights),
                )
                best = ranked[0]
                rationale = (
                    "selected_by_hybrid_score:"
                    f"{self._hybrid_score(best, cache, weights):.6f}"
                    f"(aic={self._safe_metric(best, 'aic'):.3f},"
                    f"bic={self._safe_metric(best, 'bic'):.3f},"
                    f"rmse={self._safe_metric(best, 'rmse'):.3f})"
                )

                ranking_table[spectrum_id] = [
                    {
                        "model_name": c.model_name,
                        "hybrid_score": self._hybrid_score(c, cache, weights),
                        "aic": self._safe_metric(c, "aic"),
                        "bic": self._safe_metric(c, "bic"),
                        "rmse": self._safe_metric(c, "rmse"),
                    }
                    for c in ranked
                ]
            else:
                ranked = sorted(
                    ranked_pool,
                    key=lambda c: self._safe_metric(c, metric_name),
                )
                best = ranked[0]
                rationale = f"selected_by_min_{metric_name}:{self._safe_metric(best, metric_name):.6f}"
                ranking_table[spectrum_id] = [
                    {
                        "model_name": c.model_name,
                        metric_name: self._safe_metric(c, metric_name),
                        "aic": self._safe_metric(c, "aic"),
                        "bic": self._safe_metric(c, "bic"),
                        "rmse": self._safe_metric(c, "rmse"),
                    }
                    for c in ranked
                ]

            if not selectable_candidates:
                rationale += ";selectable_candidates=0(used_all_candidates)"

            selected[spectrum_id] = SelectionResult(selected=best, rationale=rationale)
            status = str(best.params.get("fit_status", "valid")).strip().lower()
            if status not in selected_status_counts:
                status = "invalid"
            selected_status_counts[status] = selected_status_counts.get(status, 0) + 1
            if progress_enabled and (index % progress_every == 0 or index == total):
                elapsed = time.perf_counter() - t0
                print(
                    "[select] "
                    f"{index}/{total} | valid={selected_status_counts.get('valid', 0)} "
                    f"attention={selected_status_counts.get('attention', 0)} "
                    f"invalid={selected_status_counts.get('invalid', 0)} "
                    f"| elapsed={elapsed:.1f}s",
                    flush=True,
                )

        context.state["selection_count"] = len(selected)
        context.state["selection_metric_usage"] = metric_usage
        context.state["selection_rankings"] = ranking_table
        context.state["selected_fit_status_counts"] = selected_status_counts
        return selected
