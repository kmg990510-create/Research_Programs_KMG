"""Default model ensemble fitting and selection implementations."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..core.interfaces import ModelEnsembleFittingStage, ModelSelectionStage
from ..core.types import (
    BaselineResult,
    FitCandidate,
    FitEnsembleResult,
    PipelineContext,
    PreprocessedSpectrum,
    SelectionResult,
)


def _argmax(values: Sequence[float]) -> int:
    best_idx = 0
    best_val = values[0]
    for i, value in enumerate(values):
        if value > best_val:
            best_idx = i
            best_val = value
    return best_idx


class DummyModelEnsembleFitting(ModelEnsembleFittingStage):
    """
    Produce synthetic fit candidates based on config-defined model names.

    Model names are read from `context.config[modality]["models"]`.
    """

    def __init__(self, default_models: Sequence[str] | None = None) -> None:
        self.default_models = list(default_models or ["signal_tracking_stub", "flat_stub"])

    @staticmethod
    def _resolve_model_names(raw_models: Any) -> list[str]:
        if not isinstance(raw_models, list):
            return []

        names: list[str] = []
        for item in raw_models:
            if isinstance(item, str):
                names.append(item)
                continue
            if isinstance(item, dict):
                name = item.get("name")
                enabled = bool(item.get("enabled", True))
                if isinstance(name, str) and enabled:
                    names.append(name)
        return names

    def _models_for_modality(self, modality: str, context: PipelineContext) -> list[str]:
        section = context.config.get(modality, {})
        raw_models = section.get("models", self.default_models) if isinstance(section, dict) else self.default_models
        names = self._resolve_model_names(raw_models)
        return names or list(self.default_models)

    @staticmethod
    def _candidate_from_name(
        model_name: str,
        corrected_y: Sequence[float],
        x: Sequence[float],
    ) -> FitCandidate:
        peak_idx = _argmax(corrected_y)
        peak_x = float(x[peak_idx])
        peak_amp = float(corrected_y[peak_idx])
        mean_y = sum(corrected_y) / len(corrected_y)

        if model_name == "signal_tracking_stub":
            aic = -peak_amp
            return FitCandidate(
                model_name=model_name,
                params={
                    "peak_position": peak_x,
                    "peak_amplitude": peak_amp,
                },
                fitted_y=list(corrected_y),
                metrics={
                    "aic": aic,
                    "bic": aic + 1.5,
                    "rmse": 0.0,
                },
            )

        if model_name == "flat_stub":
            flat_y = [mean_y] * len(corrected_y)
            aic = abs(mean_y) + 5.0
            return FitCandidate(
                model_name=model_name,
                params={"offset": float(mean_y)},
                fitted_y=flat_y,
                metrics={
                    "aic": aic,
                    "bic": aic + 1.5,
                    "rmse": abs(mean_y),
                },
            )

        scaled_y = [0.95 * value for value in corrected_y]
        rmse = sum(abs(a - b) for a, b in zip(corrected_y, scaled_y)) / max(len(corrected_y), 1)
        aic = rmse + 1.0
        return FitCandidate(
            model_name=model_name,
            params={
                "peak_position": peak_x,
                "peak_amplitude": peak_amp * 0.95,
            },
            fitted_y=scaled_y,
            metrics={
                "aic": aic,
                "bic": aic + 1.5,
                "rmse": rmse,
            },
        )

    def run(
        self,
        spectra: Sequence[PreprocessedSpectrum],
        baselines: Mapping[str, BaselineResult],
        context: PipelineContext,
    ) -> Mapping[str, FitEnsembleResult]:
        ensemble: dict[str, FitEnsembleResult] = {}
        metadata_index = context.state.setdefault("spectrum_metadata", {})

        for spectrum in spectra:
            baseline = baselines[spectrum.spectrum_id].selected.baseline_y
            corrected_y = [v - b for v, b in zip(spectrum.y, baseline)]
            modality = str(spectrum.metadata.get("modality", "raman")).lower()
            model_names = self._models_for_modality(modality=modality, context=context)
            metadata_index[spectrum.spectrum_id] = dict(spectrum.metadata)

            candidates = [
                self._candidate_from_name(name, corrected_y=corrected_y, x=spectrum.x)
                for name in model_names
            ]
            ensemble[spectrum.spectrum_id] = FitEnsembleResult(
                modality=modality,
                candidates=candidates,
            )

        context.state["fit_count"] = len(ensemble)
        return ensemble


class FirstBestModelSelection(ModelSelectionStage):
    """
    Select candidate by modality-specific metric from YAML config.

    Supported metrics: AIC, BIC, RMSE (all minimized).
    """

    def __init__(self, default_metric: str = "aic") -> None:
        self.default_metric = default_metric.lower()

    def _metric_for_modality(self, modality: str, context: PipelineContext) -> str:
        section = context.config.get(modality, {})
        configured = (
            str(section.get("selection_metric", self.default_metric)).lower()
            if isinstance(section, dict)
            else self.default_metric
        )
        if configured in {"aic", "bic", "rmse"}:
            return configured
        return self.default_metric

    def run(
        self,
        fit_results: Mapping[str, FitEnsembleResult],
        context: PipelineContext,
    ) -> Mapping[str, SelectionResult]:
        selected: dict[str, SelectionResult] = {}
        metric_usage: dict[str, int] = {"aic": 0, "bic": 0, "rmse": 0}

        for spectrum_id, result in fit_results.items():
            if not result.candidates:
                continue

            metric_name = self._metric_for_modality(result.modality, context)
            metric_usage[metric_name] = metric_usage.get(metric_name, 0) + 1
            best = min(
                result.candidates,
                key=lambda c: c.metrics.get(metric_name, float("inf")),
            )
            selected[spectrum_id] = SelectionResult(
                selected=best,
                rationale=f"selected_by_min_{metric_name}:{best.metrics.get(metric_name, 'na')}",
            )

        context.state["selection_count"] = len(selected)
        context.state["selection_metric_usage"] = metric_usage
        return selected
