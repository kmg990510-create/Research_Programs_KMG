"""Controller layer for desktop manual refit editor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from fitting.mos2_core.core.runtime_paths import raman_config_dir
from fitting.mos2_core.io import config_access as cfgx
from fitting.mos2_core.io import load_pipeline_config
from fitting.mos2_core.review.refit_api import ManualRefitRequest, SingleSpectrumRefitAPI

from .models import EditorRequest, EditorResponse, PeakRow


_FWHM_TO_SIGMA_GAUSSIAN = 2.3548200450309493
_EPS = 1.0e-12


def _gaussian_normalized_curve(x: np.ndarray, *, center: float, sigma: float) -> np.ndarray:
    sigma_val = max(float(sigma), _EPS)
    z = (x - center) / sigma_val
    return np.exp(-0.5 * z * z) / (sigma_val * np.sqrt(2.0 * np.pi))


def _lorentz_normalized_curve(x: np.ndarray, *, center: float, sigma: float) -> np.ndarray:
    sigma_val = max(float(sigma), _EPS)
    return (1.0 / np.pi) * (sigma_val / (((x - center) ** 2) + (sigma_val * sigma_val)))


def _profiled_component_curve(
    x: np.ndarray,
    *,
    center: float,
    height: float,
    fwhm: float,
    line_profile: str,
    fraction: float,
) -> np.ndarray:
    if fwhm <= 0 or height <= 0:
        return np.zeros_like(x, dtype=float)
    profile = str(line_profile).strip().lower()
    if profile == "gaussian":
        sigma_g = max(float(fwhm) / _FWHM_TO_SIGMA_GAUSSIAN, 1.0e-6)
        area_g = float(height) * sigma_g * np.sqrt(2.0 * np.pi)
        return area_g * _gaussian_normalized_curve(x, center=float(center), sigma=sigma_g)
    if profile == "lorentz":
        sigma_l = max(float(fwhm) / 2.0, 1.0e-6)
        area_l = float(height) * np.pi * sigma_l
        return area_l * _lorentz_normalized_curve(x, center=float(center), sigma=sigma_l)

    sigma_l = max(float(fwhm) / 2.0, 1.0e-6)
    frac = float(np.clip(fraction, 0.0, 1.0))
    sigma_g = sigma_l / np.sqrt(2.0 * np.log(2.0))
    gaussian_height = 1.0 / max(sigma_g * np.sqrt(2.0 * np.pi), _EPS)
    lorentz_height = 1.0 / max(np.pi * sigma_l, _EPS)
    height_to_area_factor = (1.0 - frac) * gaussian_height + frac * lorentz_height
    area = float(height) / max(height_to_area_factor, _EPS)
    return area * (
        (1.0 - frac) * _gaussian_normalized_curve(x, center=float(center), sigma=sigma_g)
        + frac * _lorentz_normalized_curve(x, center=float(center), sigma=sigma_l)
    )


class ManualEditorController:
    """Owns editor state and computes preview curves."""

    def __init__(self, request: EditorRequest) -> None:
        self.request = request
        self.x = np.asarray(request.x, dtype=float)
        self.y = np.asarray(request.y, dtype=float)
        self.peaks: list[PeakRow] = list(request.peaks)
        self.operator_note: str = ""
        self._refit_api = SingleSpectrumRefitAPI()
        self._line_profile = self._resolve_line_profile(request.row_snapshot)
        self._compare_x_min, self._compare_x_max = self._resolve_compare_window()
        self._initial_rmse: float | None = None
        self._initial_aic: float | None = None
        initial = self._compute_preview_metrics()
        self._initial_rmse = initial.rmse
        self._initial_aic = initial.aic

    def set_peaks(self, peaks: list[PeakRow]) -> None:
        self.peaks = peaks

    def set_operator_note(self, value: str) -> None:
        self.operator_note = value.strip()

    def preview_curve(self) -> np.ndarray:
        if self.x.size == 0:
            return np.array([], dtype=float)
        baseline = self._baseline_curve()
        y_fit = np.array(baseline, dtype=float)
        for peak in self.peaks:
            y_fit += _profiled_component_curve(
                self.x,
                center=float(peak.center),
                height=float(max(peak.height, 0.0)),
                fwhm=float(max(peak.fwhm, 1.0e-6)),
                line_profile=self._line_profile,
                fraction=float(np.clip(peak.fraction, 0.0, 1.0)),
            )
        return y_fit

    def preview_metrics(self) -> "PreviewMetrics":
        current = self._compute_preview_metrics()
        rmse_delta = (
            current.rmse - self._initial_rmse
            if self._initial_rmse is not None and current.rmse is not None
            else None
        )
        aic_delta = (
            current.aic - self._initial_aic
            if self._initial_aic is not None and current.aic is not None
            else None
        )
        return PreviewMetrics(
            rmse=current.rmse,
            aic=current.aic,
            initial_rmse=self._initial_rmse,
            initial_aic=self._initial_aic,
            rmse_delta=rmse_delta,
            aic_delta=aic_delta,
            n_points=current.n_points,
            n_params=current.n_params,
        )

    def _compute_preview_metrics(self) -> "PreviewMetrics":
        if self.x.size == 0 or self.y.size == 0:
            return PreviewMetrics(
                rmse=None,
                aic=None,
                initial_rmse=None,
                initial_aic=None,
                rmse_delta=None,
                aic_delta=None,
                n_points=0,
                n_params=0,
            )

        y_fit = self.preview_curve()
        finite_mask = np.isfinite(self.y) & np.isfinite(y_fit) & np.isfinite(self.x)
        finite_mask &= (self.x >= self._compare_x_min) & (self.x <= self._compare_x_max)
        if not bool(np.any(finite_mask)):
            return PreviewMetrics(
                rmse=None,
                aic=None,
                initial_rmse=None,
                initial_aic=None,
                rmse_delta=None,
                aic_delta=None,
                n_points=0,
                n_params=0,
            )

        residual = self.y[finite_mask] - y_fit[finite_mask]
        n_points = int(residual.size)
        sse = float(np.sum(np.square(residual)))
        mse = max(sse / max(n_points, 1), 1.0e-12)
        rmse = float(np.sqrt(mse))
        n_params = self._effective_param_count()
        aic = float(n_points * np.log(mse) + 2.0 * max(n_params, 1))
        return PreviewMetrics(
            rmse=rmse,
            aic=aic,
            initial_rmse=None,
            initial_aic=None,
            rmse_delta=None,
            aic_delta=None,
            n_points=n_points,
            n_params=n_params,
        )

    def run_auto_fit(self) -> dict[str, Any]:
        payload = {
            "spectrum_id": self.request.spectrum_id,
            "modality": self.request.modality,
            "source_file": self.request.source_file,
            "selected_model": self.request.selected_model,
            "calibration_offset": float(self.request.calibration_offset),
            "report_path": self.request.report_path,
            "x": [float(v) for v in self.x.tolist()],
            "y": [float(v) for v in self.y.tolist()],
            "peaks": [peak.to_payload() for peak in self.peaks],
            "reason": "desktop_auto_fit",
            "operator_note": self.operator_note,
        }
        refit_request = ManualRefitRequest.from_payload(payload)
        result = self._refit_api.submit_auto_refit(refit_request)
        if str(result.get("status", "")).lower() != "ok":
            raise RuntimeError(str(result.get("message", "auto fit failed")))
        params = result.get("params", {})
        if not isinstance(params, dict):
            raise RuntimeError("auto fit returned invalid params payload")
        self._apply_peak_params(params)
        selected_model = str(result.get("selected_model", "")).strip()
        if selected_model:
            self.request.selected_model = selected_model
        return result

    def build_response(self) -> dict[str, Any]:
        payload = EditorResponse(
            spectrum_id=self.request.spectrum_id,
            modality=self.request.modality,
            selected_model=self.request.selected_model,
            peaks=self.peaks,
            operator_note=self.operator_note,
        ).to_payload()
        payload["report_path"] = self.request.report_path
        payload["source_file"] = self.request.source_file
        return payload

    def _baseline_curve(self) -> np.ndarray:
        slope = self._safe_metric(self.request.row_snapshot.get("bg_slope"))
        intercept = self._safe_metric(self.request.row_snapshot.get("bg_intercept"))
        if slope is None or intercept is None:
            if self.x.size >= 2 and self.y.size >= 2:
                x0 = float(self.x[0])
                x1 = float(self.x[-1])
                y0 = float(self.y[0])
                y1 = float(self.y[-1])
                slope = float((y1 - y0) / max(x1 - x0, 1.0e-9))
                intercept = float(y0 - slope * x0)
            else:
                slope, intercept = 0.0, 0.0
        return slope * self.x + intercept

    def _effective_param_count(self) -> int:
        n_peak_params = 0
        for peak in self.peaks:
            n_peak_params += 0 if peak.fixed_center else 1
            n_peak_params += 0 if peak.fixed_height else 1
            n_peak_params += 0 if peak.fixed_fwhm else 1
            if self._line_profile not in {"gaussian", "lorentz"}:
                n_peak_params += 0 if peak.fixed_fraction else 1
        # linear baseline slope/intercept
        return max(1, n_peak_params + 2)

    def _resolve_compare_window(self) -> tuple[float, float]:
        modality = str(self.request.modality or "raman").strip().lower()
        config = load_pipeline_config(raman_config_dir())
        fit_cfg = cfgx.section(cfgx.section(config, modality, ""), "fit", modality)
        x_min = cfgx.number(fit_cfg, "compare_x_min", f"{modality}.fit")
        x_max = cfgx.number(fit_cfg, "compare_x_max", f"{modality}.fit")
        return x_min, x_max

    @staticmethod
    def _resolve_line_profile(row_snapshot: dict[str, Any]) -> str:
        profile = str(row_snapshot.get("line_profile", "") or "").strip().lower()
        if profile in {"gaussian", "lorentz", "pvoigt"}:
            return profile
        model_name = str(row_snapshot.get("selected_model", "") or "").strip().lower()
        if "gaussian" in model_name:
            return "gaussian"
        if "lorentz" in model_name:
            return "lorentz"
        return "pvoigt"

    @staticmethod
    def _safe_metric(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not np.isfinite(number):
            return None
        return float(number)

    def _apply_peak_params(self, params: dict[str, Any]) -> None:
        for peak in self.peaks:
            peak_name = str(peak.peak).strip().lower()
            center = self._safe_metric(params.get(f"{peak_name}_position"))
            height = self._safe_metric(params.get(f"{peak_name}_height"))
            fwhm = self._safe_metric(params.get(f"{peak_name}_fwhm"))
            fraction = self._safe_metric(params.get(f"{peak_name}_fraction"))
            if center is not None:
                peak.center = float(center)
            if height is not None:
                peak.height = float(max(height, 0.0))
            if fwhm is not None:
                peak.fwhm = float(max(fwhm, 1.0e-6))
            if fraction is not None:
                peak.fraction = float(np.clip(fraction, 0.0, 1.0))


@dataclass(slots=True)
class PreviewMetrics:
    rmse: float | None
    aic: float | None
    initial_rmse: float | None
    initial_aic: float | None
    rmse_delta: float | None
    aic_delta: float | None
    n_points: int
    n_params: int
