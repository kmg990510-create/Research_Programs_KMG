"""APIs for manual refit requests from GUI workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from lmfit.models import LinearModel, PseudoVoigtModel

from ..core.default_stages import build_default_context
from ..fitting import LmfitRamanModelEnsembleFitting
from ..fitting.raman_lmfit import (
    _build_n_peak_spec,
    _estimate_linear_baseline_edges,
    _height_guess_to_lmfit_area,
    _sigma_bounds_for_peak,
)
from ..io import parse_raman_txt

@dataclass(slots=True)
class ManualPeakOverride:
    """One editable peak override entry from manual editor."""

    peak: str
    center: float | None = None
    height: float | None = None
    fwhm: float | None = None
    fraction: float | None = None
    fixed_fraction: bool = False
    fixed_center: bool = False
    fixed_height: bool = False
    fixed_fwhm: bool = False


@dataclass(slots=True)
class ManualRefitRequest:
    """User-triggered single-spectrum manual refit payload."""

    spectrum_id: str
    modality: str
    source_file: str
    model_name: str
    calibration_offset: float = 0.0
    report_path: str = ""
    x: list[float] = field(default_factory=list)
    y: list[float] = field(default_factory=list)
    peaks: list[ManualPeakOverride] = field(default_factory=list)
    parameter_overrides: Mapping[str, Any] = field(default_factory=dict)
    reason: str = ""
    operator_note: str = ""

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ManualRefitRequest":
        peak_rows: list[ManualPeakOverride] = []
        for item in payload.get("peaks", []) if isinstance(payload.get("peaks"), list) else []:
            if not isinstance(item, Mapping):
                continue
            peak_rows.append(
                ManualPeakOverride(
                    peak=str(item.get("peak", "")).strip().lower(),
                    center=_to_float(item.get("center")),
                    height=_to_float(item.get("height")),
                    fwhm=_to_float(item.get("fwhm")),
                    fraction=_to_float(item.get("fraction")),
                    fixed_fraction=bool(item.get("fixed_fraction", False)),
                    fixed_center=bool(item.get("fixed_center", False)),
                    fixed_height=bool(item.get("fixed_height", False)),
                    fixed_fwhm=bool(item.get("fixed_fwhm", False)),
                )
            )
        return cls(
            spectrum_id=str(payload.get("spectrum_id", "")).strip(),
            modality=str(payload.get("modality", "raman")).strip().lower() or "raman",
            source_file=str(payload.get("source_file", "")).strip(),
            model_name=str(payload.get("selected_model", payload.get("model_name", ""))).strip(),
            calibration_offset=_to_float(payload.get("calibration_offset"), default=0.0) or 0.0,
            report_path=str(payload.get("report_path", "")).strip(),
            x=[float(v) for v in payload.get("x", [])] if isinstance(payload.get("x"), list) else [],
            y=[float(v) for v in payload.get("y", [])] if isinstance(payload.get("y"), list) else [],
            peaks=peak_rows,
            parameter_overrides=(
                payload.get("parameter_overrides", {})
                if isinstance(payload.get("parameter_overrides"), Mapping)
                else {}
            ),
            reason=str(payload.get("reason", "manual_refit")).strip(),
            operator_note=str(payload.get("operator_note", "")).strip(),
        )


@dataclass(slots=True)
class ManualRefitResult:
    """Normalized result payload for manual refit execution."""

    status: str
    spectrum_id: str
    modality: str
    selected_model: str
    params: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    fitted_y: list[float] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "spectrum_id": self.spectrum_id,
            "modality": self.modality,
            "selected_model": self.selected_model,
            "params": self.params,
            "metrics": self.metrics,
            "fitted_y": self.fitted_y,
            "warnings": self.warnings,
        }


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fwhm_to_sigma(line_profile: str, fwhm: float) -> float:
    if fwhm <= 0:
        return 1.0
    if line_profile == "gaussian":
        return max(float(fwhm) / 2.354820045, 1.0e-6)
    return max(float(fwhm) / 2.0, 1.0e-6)


_EPS = 1.0e-12


def _gaussian_normalized_curve(x: np.ndarray, *, center: float, sigma: float) -> np.ndarray:
    sigma_val = max(float(sigma), _EPS)
    z = (x - center) / sigma_val
    return np.exp(-0.5 * z * z) / (sigma_val * np.sqrt(2.0 * np.pi))


def _lorentz_normalized_curve(x: np.ndarray, *, center: float, sigma: float) -> np.ndarray:
    sigma_val = max(float(sigma), _EPS)
    return (1.0 / np.pi) * (sigma_val / (((x - center) ** 2) + (sigma_val * sigma_val)))


def _component_curve_from_height_fwhm(
    x: np.ndarray,
    center: float,
    height: float,
    fwhm: float,
    line_profile: str,
    fraction: float,
) -> np.ndarray:
    if fwhm <= 0 or height <= 0:
        return np.zeros_like(x, dtype=float)
    profile = line_profile.strip().lower()
    if profile == "gaussian":
        sigma_g = max(float(fwhm) / 2.354820045, 1.0e-6)
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


def _component_curve_from_area_sigma(
    x: np.ndarray,
    *,
    center: float,
    area: float,
    sigma: float,
    line_profile: str,
    fraction: float,
) -> np.ndarray:
    if sigma <= 0 or area <= 0:
        return np.zeros_like(x, dtype=float)
    profile = line_profile.strip().lower()
    if profile == "gaussian":
        return float(area) * _gaussian_normalized_curve(x, center=float(center), sigma=float(sigma))
    if profile == "lorentz":
        return float(area) * _lorentz_normalized_curve(x, center=float(center), sigma=float(sigma))

    frac = float(np.clip(fraction, 0.0, 1.0))
    sigma_l = float(max(sigma, 1.0e-6))
    sigma_g = sigma_l / np.sqrt(2.0 * np.log(2.0))
    return float(area) * (
        (1.0 - frac) * _gaussian_normalized_curve(x, center=float(center), sigma=sigma_g)
        + frac * _lorentz_normalized_curve(x, center=float(center), sigma=sigma_l)
    )


_PL_PEAKS = ("i1", "i2", "a_minus", "a0", "b", "pl")
_RAMAN_PEAKS = ("lo", "e2g", "a1g", "zo", "la")


def _synthesize_fitted_y(x: np.ndarray, params: Mapping[str, Any], modality: str = "") -> np.ndarray:
    profile = str(params.get("line_profile", "pvoigt")).strip().lower()
    bg_slope = _to_float(params.get("bg_slope"), 0.0) or 0.0
    bg_intercept = _to_float(params.get("bg_intercept"), 0.0) or 0.0
    baseline = bg_slope * x + bg_intercept
    y_fit = baseline.copy()

    pl_component_peaks = ("i1", "i2", "a_minus", "a0", "b")
    has_explicit_pl_components = any(
        _to_float(params.get(f"{peak}_position")) is not None
        for peak in pl_component_peaks
    )
    modality_key = str(modality or params.get("modality", "")).strip().lower()
    if modality_key == "raman":
        peak_names = _RAMAN_PEAKS
    elif modality_key == "pl":
        peak_names = _PL_PEAKS
    else:
        peak_names = _PL_PEAKS + _RAMAN_PEAKS
    for peak in peak_names:
        if peak == "pl" and has_explicit_pl_components:
            continue
        center = _to_float(params.get(f"{peak}_position"))
        area = _to_float(params.get(f"{peak}_area"))
        sigma = _to_float(params.get(f"{peak}_sigma"))
        height = _to_float(params.get(f"{peak}_height"))
        fwhm = _to_float(params.get(f"{peak}_fwhm"))
        fraction = _to_float(params.get(f"{peak}_fraction"), 0.0) or 0.0
        peak_profile = str(params.get(f"{peak}_line_profile", profile)).strip().lower()
        if center is None:
            continue
        if area is not None and sigma is not None and sigma > 0:
            y_fit += _component_curve_from_area_sigma(
                x,
                center=float(center),
                area=float(max(area, 0.0)),
                sigma=float(sigma),
                line_profile=peak_profile,
                fraction=float(fraction),
            )
            continue
        if height is None or fwhm is None:
            continue
        y_fit += _component_curve_from_height_fwhm(
            x=x,
            center=float(center),
            height=float(max(height, 0.0)),
            fwhm=float(max(fwhm, 1.0e-6)),
            line_profile=peak_profile,
            fraction=float(fraction),
        )
    return y_fit


class SingleSpectrumRefitAPI:
    """Single-spectrum manual refit adapter reused by Streamlit and desktop UI."""

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = (project_root or Path(__file__).resolve().parents[3]).resolve()
        self.config_dir = self.project_root / "fitting" / "mos2_raman" / "config"

    def submit_refit(self, request: ManualRefitRequest) -> dict[str, Any]:
        return self.run_manual_refit(request).to_payload()

    def submit_auto_refit(self, request: ManualRefitRequest) -> dict[str, Any]:
        return self.run_auto_refit(request).to_payload()

    def run_manual_refit(self, request: ManualRefitRequest) -> ManualRefitResult:
        if not request.spectrum_id:
            raise ValueError("spectrum_id is required")
        if not request.model_name:
            raise ValueError("model_name is required")

        x_arr, y_arr = self._resolve_xy(request)
        modality = request.modality if request.modality in {"raman", "pl"} else "raman"

        context = build_default_context(
            run_id="manual_refit",
            artifact_dir=self.project_root,
            config_dir=self.config_dir,
        )
        fitter = LmfitRamanModelEnsembleFitting(enable_pl=True)
        cfg = fitter._resolve_fit_config(context, modality=modality)  # noqa: SLF001
        base_candidate = fitter._fit_candidate(  # noqa: SLF001
            model_name=request.model_name,
            x_full=x_arr,
            y_corr=y_arr,
            cfg=cfg,
            anchor_centers=None,
            modality=modality,
        )

        params = dict(base_candidate.params)
        warnings: list[str] = []
        line_profile = str(params.get("line_profile", "pvoigt")).strip().lower()
        for peak_row in request.peaks:
            peak = peak_row.peak
            if peak not in {"i1", "i2", "a_minus", "a0", "b", "pl", "lo", "e2g", "a1g", "zo", "la"}:
                warnings.append(f"ignored_unknown_peak:{peak}")
                continue
            if peak_row.center is not None:
                params[f"{peak}_position"] = float(peak_row.center)
            if peak_row.height is not None:
                params[f"{peak}_height"] = float(max(peak_row.height, 0.0))
            if peak_row.fwhm is not None:
                params[f"{peak}_fwhm"] = float(max(peak_row.fwhm, 1.0e-6))
                sigma = _fwhm_to_sigma(line_profile=line_profile, fwhm=float(peak_row.fwhm))
                params[f"{peak}_sigma"] = sigma
            if peak_row.fraction is not None:
                params[f"{peak}_fraction"] = float(np.clip(peak_row.fraction, 0.0, 1.0))
            if (
                params.get(f"{peak}_height") is not None
                and params.get(f"{peak}_fwhm") is not None
            ):
                sigma_guess = _to_float(params.get(f"{peak}_sigma"), 1.0) or 1.0
                fraction = _to_float(params.get(f"{peak}_fraction"), 0.0) or 0.0
                params[f"{peak}_area"] = _height_guess_to_lmfit_area(
                    height_guess=float(params[f"{peak}_height"]),
                    sigma_guess=float(sigma_guess),
                    fraction_guess=float(fraction),
                )

        if "e2g_position" in params and "a1g_position" in params:
            e2g = _to_float(params.get("e2g_position"))
            a1g = _to_float(params.get("a1g_position"))
            if e2g is not None and a1g is not None:
                params["delta_e2g_a1g"] = float(a1g - e2g)

        y_fit = _synthesize_fitted_y(x_arr, params, modality)
        base_candidate.params = params
        base_candidate.fitted_y = [float(v) for v in y_fit]
        fitter._recompute_metrics_on_window(  # noqa: SLF001
            base_candidate,
            x_full=x_arr,
            y_true=y_arr,
            x_min=cfg.compare_x_min,
            x_max=cfg.compare_x_max,
        )
        params["fit_status"] = "attention"
        reasons = params.get("attention_reasons", [])
        if not isinstance(reasons, list):
            reasons = []
        if "manual_refit" not in reasons:
            reasons.append("manual_refit")
        params["attention_reasons"] = reasons
        params["invalid_reasons"] = []

        return ManualRefitResult(
            status="ok",
            spectrum_id=request.spectrum_id,
            modality=modality,
            selected_model=request.model_name,
            params=params,
            metrics=dict(base_candidate.metrics),
            fitted_y=[float(v) for v in y_fit],
            warnings=warnings,
        )

    def run_auto_refit(self, request: ManualRefitRequest) -> ManualRefitResult:
        if not request.spectrum_id:
            raise ValueError("spectrum_id is required")
        if not request.model_name:
            raise ValueError("model_name is required")

        x_arr, y_arr = self._resolve_xy(request)
        modality = request.modality if request.modality in {"raman", "pl"} else "raman"

        context = build_default_context(
            run_id="manual_autofit",
            artifact_dir=self.project_root,
            config_dir=self.config_dir,
        )
        fitter = LmfitRamanModelEnsembleFitting(enable_pl=True)
        cfg = fitter._resolve_fit_config(context, modality=modality)  # noqa: SLF001

        warnings: list[str] = []
        if modality == "raman" and request.model_name in {"peak_2_model", "peak_3_model", "peak_4_model", "peak_5_model"}:
            auto_candidate = self._fit_n_peak_candidate_with_initial(
                fitter=fitter,
                model_name=request.model_name,
                x_full=x_arr,
                y_corr=y_arr,
                cfg=cfg,
                peak_rows=request.peaks,
                parameter_overrides=request.parameter_overrides,
            )
        else:
            warnings.append("autofit_fallback_to_default_candidate")
            auto_candidate = fitter._fit_candidate(  # noqa: SLF001
                model_name=request.model_name,
                x_full=x_arr,
                y_corr=y_arr,
                cfg=cfg,
                anchor_centers=None,
                modality=modality,
            )

        params = dict(auto_candidate.params)
        y_fit = np.asarray(auto_candidate.fitted_y, dtype=float)
        if y_fit.size != x_arr.size:
            y_fit = _synthesize_fitted_y(x_arr, params, modality)
        params["fit_status"] = "attention"
        reasons = params.get("attention_reasons", [])
        if not isinstance(reasons, list):
            reasons = []
        if "manual_refit_autofit" not in reasons:
            reasons.append("manual_refit_autofit")
        params["attention_reasons"] = reasons
        params["invalid_reasons"] = []

        return ManualRefitResult(
            status="ok",
            spectrum_id=request.spectrum_id,
            modality=modality,
            selected_model=request.model_name,
            params=params,
            metrics=dict(auto_candidate.metrics),
            fitted_y=[float(v) for v in y_fit.tolist()],
            warnings=warnings,
        )

    def _resolve_xy(self, request: ManualRefitRequest) -> tuple[np.ndarray, np.ndarray]:
        if request.x and request.y and len(request.x) == len(request.y):
            x_arr = np.asarray(request.x, dtype=float)
            y_arr = np.asarray(request.y, dtype=float)
        else:
            source = Path(request.source_file)
            if not source.is_absolute():
                source = (self.project_root / source).resolve()
            spectrum = parse_raman_txt(source)
            x_arr = np.asarray(spectrum.x, dtype=float)
            y_arr = np.asarray(spectrum.y, dtype=float)
        if abs(request.calibration_offset) > 0:
            x_arr = x_arr + float(request.calibration_offset)
        return x_arr, y_arr

    def _fit_n_peak_candidate_with_initial(
        self,
        *,
        fitter: LmfitRamanModelEnsembleFitting,
        model_name: str,
        x_full: np.ndarray,
        y_corr: np.ndarray,
        cfg: Any,
        peak_rows: list[ManualPeakOverride],
        parameter_overrides: Mapping[str, Any],
    ) -> Any:
        spec = _build_n_peak_spec(model_name, cfg)
        mask = fitter._mask_roi(x_full, spec.x_min, spec.x_max)  # noqa: SLF001
        x_fit = x_full[mask]
        y_fit = y_corr[mask]
        if x_fit.size < 20:
            raise ValueError(f"Insufficient ROI points for model {model_name}")

        baseline_slope, baseline_intercept = _estimate_linear_baseline_edges(
            x_fit, y_fit, spec.left_base, spec.right_base
        )
        bg_slope_override = _to_float(parameter_overrides.get("bg_slope"))
        bg_intercept_override = _to_float(parameter_overrides.get("bg_intercept"))
        if bg_slope_override is not None:
            baseline_slope = float(bg_slope_override)
        if bg_intercept_override is not None:
            baseline_intercept = float(bg_intercept_override)

        h_guess = max(float(np.max(y_fit) - np.min(y_fit)), 1.0)
        peak_overrides = {
            str(item.peak).strip().lower(): item
            for item in peak_rows
            if isinstance(item.peak, str) and str(item.peak).strip()
        }

        model = LinearModel(prefix="bg_")
        prefix_for_label: dict[str, str] = {}
        for idx, label in enumerate(spec.peak_labels):
            prefix = f"p{idx}_"
            prefix_for_label[label] = prefix
            model += PseudoVoigtModel(prefix=prefix)

        params = model.make_params()
        if spec.lock_baseline:
            a_eps = max(1.0e-8, abs(baseline_slope) * 0.01)
            b_eps = max(1.0e-8, abs(baseline_intercept) * 0.01)
            params["bg_slope"].set(value=baseline_slope, min=baseline_slope - a_eps, max=baseline_slope + a_eps)
            params["bg_intercept"].set(
                value=baseline_intercept,
                min=baseline_intercept - b_eps,
                max=baseline_intercept + b_eps,
            )
        else:
            params["bg_slope"].set(value=baseline_slope, min=-2.0, max=2.0)
            params["bg_intercept"].set(value=baseline_intercept)

        for idx, label in enumerate(spec.peak_labels):
            prefix = prefix_for_label[label]
            peak_key = str(label).strip().lower()
            peak_override = peak_overrides.get(peak_key)

            center_guess = float(spec.center_guesses[idx])
            width_guess = float(spec.width_guesses[idx])
            height_guess = float(spec.height_scales[idx] * h_guess)
            fraction_guess = _to_float(parameter_overrides.get(f"{peak_key}_fraction"), default=0.0) or 0.0

            if peak_override is not None:
                if peak_override.center is not None:
                    center_guess = float(peak_override.center)
                if peak_override.height is not None:
                    height_guess = float(max(peak_override.height, 0.0))
                if peak_override.fwhm is not None:
                    width_guess = max(float(peak_override.fwhm) / 2.0, 1.0e-6)
                if peak_override.fraction is not None:
                    fraction_guess = float(np.clip(peak_override.fraction, 0.0, 1.0))

            if label == "E2g":
                center_min, center_max = cfg.e2g_bounds
            elif label == "A1g":
                center_min, center_max = cfg.a1g_bounds
            else:
                center_min = center_guess - spec.center_tolerance
                center_max = center_guess + spec.center_tolerance
            center_guess = float(np.clip(center_guess, center_min, center_max))

            sigma_min, sigma_max = _sigma_bounds_for_peak(cfg, label)
            sigma_guess = float(np.clip(width_guess, sigma_min, sigma_max))
            area_guess_lmfit = _height_guess_to_lmfit_area(
                height_guess=height_guess,
                sigma_guess=sigma_guess,
                fraction_guess=fraction_guess,
            )

            center_vary = not bool(peak_override.fixed_center) if peak_override is not None else True
            sigma_vary = not bool(peak_override.fixed_fwhm) if peak_override is not None else True
            amp_vary = not bool(peak_override.fixed_height) if peak_override is not None else True
            frac_vary = not bool(peak_override.fixed_fraction) if peak_override is not None else True

            params[f"{prefix}center"].set(value=center_guess, min=center_min, max=center_max, vary=center_vary)
            params[f"{prefix}sigma"].set(value=sigma_guess, min=sigma_min, max=sigma_max, vary=sigma_vary)
            params[f"{prefix}amplitude"].set(value=max(area_guess_lmfit, 1.0e-6), min=0.0, vary=amp_vary)
            params[f"{prefix}fraction"].set(
                value=float(np.clip(fraction_guess, 0.0, 1.0)),
                min=0.0,
                max=1.0,
                vary=frac_vary,
            )

        fit_result = model.fit(y_fit, params, x=x_fit, nan_policy="omit")
        y_pred_full = model.eval(fit_result.params, x=x_full)
        return fitter._candidate_from_result(  # noqa: SLF001
            model_name=model_name,
            fit_result=fit_result,
            x_fit=x_fit,
            y_fit=y_fit,
            x_full=x_full,
            y_pred_full=np.asarray(y_pred_full, dtype=float),
            peak_labels=spec.peak_labels,
            prefix_for_label=prefix_for_label,
        )


def build_manual_refit_record(
    *,
    request_payload: Mapping[str, Any],
    result_payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "manual_refit_record.v1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "report_path": str(request_payload.get("report_path", "")),
        "spectrum_id": str(request_payload.get("spectrum_id", "")),
        "modality": str(request_payload.get("modality", "")),
        "source_file": str(request_payload.get("source_file", "")),
        "selected_model_before": str(
            request_payload.get(
                "selected_model",
                request_payload.get("model_name", ""),
            )
        ),
        "selected_model_after": str(result_payload.get("selected_model", "")),
        "overrides": request_payload.get("peaks", []),
        "refit_result": {
            "status": result_payload.get("status"),
            "params": result_payload.get("params", {}),
            "metrics": result_payload.get("metrics", {}),
            "fit_status": (
                result_payload.get("params", {}).get("fit_status")
                if isinstance(result_payload.get("params"), Mapping)
                else None
            ),
        },
        "operator_note": str(request_payload.get("operator_note", "")),
        "editor": "pyside6_pyqtgraph",
    }
