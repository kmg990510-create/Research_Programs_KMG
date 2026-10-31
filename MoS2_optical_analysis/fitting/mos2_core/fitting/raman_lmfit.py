"""LMFIT-based Raman model ensemble fitting implementations."""

from __future__ import annotations

import concurrent.futures
import os
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
from lmfit.model import ModelResult
from lmfit.models import GaussianModel, LinearModel, PseudoVoigtModel

from ..core.interfaces import ModelEnsembleFittingStage
from ..core.types import BaselineResult, FitCandidate, FitEnsembleResult, PipelineContext, PreprocessedSpectrum
from ..io import config_access as cfgx


@dataclass(slots=True)
class NPeakWindowSpec:
    """ROI and baseline-edge windows for one N-peak model."""

    x_min: float
    x_max: float
    left_base: tuple[float, float]
    right_base: tuple[float, float]


RAMAN_PEAK_MODELS = ("peak_2_model", "peak_3_model", "peak_4_model", "peak_5_model")
RAMAN_PEAK_LABELS = {
    "peak_2_model": ["E2g", "A1g"],
    "peak_3_model": ["LO", "E2g", "A1g"],
    "peak_4_model": ["LO", "E2g", "A1g", "ZO"],
    "peak_5_model": ["LO", "E2g", "A1g", "ZO", "LA"],
}
_OFFSET_BOUND_KEYS = {
    "lo_from_e2g": ("min", "max"),
    "zo_from_a1g": ("min", "max_floor", "max_margin"),
    "la_from_a1g": ("min", "max_floor", "max_margin"),
    "chain": ("guess_floor", "min", "max"),
}


@dataclass(slots=True)
class RamanFitConfig:
    """Runtime fit configuration resolved strictly from config.yaml (`raman.fit` or `pl.fit`).

    Fields that only one modality uses are left neutral for the other one.
    """

    models: list[str]
    x_min: float
    x_max: float
    e2g_init: float
    a1g_init: float
    lo_offset_from_e2g: float
    zo_offset_from_a1g: float
    la_offset_from_a1g: float
    height_scales: dict[str, list[float]]
    center_tolerance_by_model: dict[str, float]
    e2g_bounds: tuple[float, float]
    a1g_bounds: tuple[float, float]
    sigma_bounds_by_peak: dict[str, tuple[float, float]]
    compare_x_min: float
    compare_x_max: float
    enforce_peak_order: bool
    two_stage_anchor_enabled: bool
    two_stage_anchor_window: float
    auto_refine_enabled: bool
    auto_refine_min_rmse_improvement: float
    prefit: "PreFitConfig"
    model_windows: dict[str, NPeakWindowSpec]
    pl_components: dict[str, "PLComponentSpec"]
    pl_model_components: dict[str, list[str]]
    pl_a_minus_a0_split: tuple[bool, float, float, float]
    pl_trion_exciton_fwhm_ratio: tuple[bool, float, float, float]
    pl_share_exciton_fraction: bool
    pl_spike_residual_sigma_k: float
    pl_spike_span_ratio: float
    pl_spike_span_percentiles: tuple[float, float]
    sigma_init_by_peak: dict[str, float]
    fraction_init: float
    lock_baseline_by_model: dict[str, bool]
    locked_baseline_rel_tol: float
    bg_slope_min_half_width: float
    bg_slope_multiplier: float
    manual_refit_bg_slope_bound: float
    baseline_edge_fraction: float
    baseline_edge_min: float
    anchor_fallback_half_window: float
    offset_bounds: dict[str, dict[str, float]]
    min_roi_points: int
    min_spectrum_points: int
    pl_seed_baseline_percentile: float
    pl_seed_local_baseline_percentile: float
    pl_seed_local_half_width_min: float
    pl_amplitude_floor_fraction: float


@dataclass(slots=True)
class PreFitConfig:
    """Configuration for pre-fit peak-evidence gating (Raman only)."""

    enabled: bool
    peak_window_half_width: float
    e2g_snr_hard_min: float
    e2g_snr_soft_min: float
    a1g_snr_hard_min: float
    a1g_snr_soft_min: float
    noise_left: tuple[float, float]
    noise_right: tuple[float, float]
    min_points: int
    noise_min_points: int
    noise_fallback_percentile: float
    noise_fallback_min_points: int
    local_baseline_percentile: float

    @classmethod
    def disabled(cls) -> "PreFitConfig":
        nan = float("nan")
        return cls(
            enabled=False,
            peak_window_half_width=nan,
            e2g_snr_hard_min=nan,
            e2g_snr_soft_min=nan,
            a1g_snr_hard_min=nan,
            a1g_snr_soft_min=nan,
            noise_left=(nan, nan),
            noise_right=(nan, nan),
            min_points=0,
            noise_min_points=0,
            noise_fallback_percentile=nan,
            noise_fallback_min_points=0,
            local_baseline_percentile=nan,
        )


@dataclass(slots=True)
class PreFitEvaluation:
    """Result of pre-fit MoS2 peak evidence checks."""

    status: str  # valid | attention | invalid
    invalid_reasons: list[str]
    attention_reasons: list[str]
    metrics: dict[str, float]


@dataclass(slots=True)
class NPeakSpec:
    """Specification for one n-peak fitting candidate model."""

    model_name: str
    peak_labels: list[str]
    center_guesses: list[float]
    width_guesses: list[float]
    height_scales: list[float]
    x_min: float
    x_max: float
    left_base: tuple[float, float]
    right_base: tuple[float, float]
    center_tolerance: float
    lock_baseline: bool


@dataclass(slots=True)
class PLComponentSpec:
    """One configured PL emission component."""

    key: str
    label: str
    profile: str
    center_init: float
    center_min: float
    center_max: float
    sigma_init: float
    sigma_min: float
    sigma_max: float
    height_scale: float
    amplitude_min: float
    fraction_init: float
    vary_center: bool
    vary_sigma: bool
    vary_amplitude: bool
    vary_fraction: bool


@dataclass(slots=True)
class _SpectrumFitResult:
    """Per-spectrum fitting bundle used by sequential/parallel execution paths."""

    spectrum_id: str
    modality: str
    candidates: list[FitCandidate]
    prefit_info: dict[str, Any]
    failures: list[dict[str, str]]


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if np.isfinite(number) else default


def _safe_param(params: Any, name: str, default: float = 0.0) -> float:
    param = params.get(name)
    if param is None:
        return default
    return _finite(getattr(param, "value", default), default=default)


def _resolve_models(section: Mapping[str, Any], path: str) -> list[str]:
    names = cfgx.string_list(section, "models", path)
    if not names:
        raise cfgx.ConfigKeyError(f"config.yaml: '{path}.models' must list at least one model")
    return names


def _pl_component_key(name: str) -> str:
    normalized = str(name).strip().lower().replace("-", "_minus")
    normalized = normalized.replace("+", "_plus")
    normalized = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in normalized)
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_") or "component"


def _fwhm_to_sigma(fwhm: float, profile: str) -> float:
    # Exact line-shape conversions (lmfit): Gaussian FWHM = 2*sqrt(2 ln2)*sigma, pseudo-Voigt FWHM = 2*sigma.
    fwhm_value = max(float(fwhm), 1.0e-9)
    return fwhm_value / 2.354820045 if profile == "gaussian" else fwhm_value / 2.0


def _resolve_pl_components(raw: Mapping[str, Any], path: str) -> dict[str, PLComponentSpec]:
    resolved: dict[str, PLComponentSpec] = {}
    for raw_name in raw:
        spec_path = f"{path}.{raw_name}"
        spec = cfgx.section(raw, raw_name, path)
        key = _pl_component_key(str(raw_name))
        profile = cfgx.text(spec, "profile", spec_path).lower()
        if profile not in {"pvoigt", "gaussian"}:
            raise cfgx.ConfigKeyError(f"config.yaml: '{spec_path}.profile' must be pvoigt or gaussian (got {profile!r})")

        center_init = cfgx.number(spec, "center_init", spec_path)
        center_min = cfgx.number(spec, "center_min", spec_path)
        center_max = cfgx.number(spec, "center_max", spec_path)
        if not center_min < center_max:
            raise cfgx.ConfigKeyError(f"config.yaml: '{spec_path}' needs center_min < center_max")
        sigma_init = _fwhm_to_sigma(cfgx.number(spec, "fwhm_init", spec_path), profile)
        sigma_min = _fwhm_to_sigma(cfgx.number(spec, "fwhm_min", spec_path), profile)
        sigma_max = _fwhm_to_sigma(cfgx.number(spec, "fwhm_max", spec_path), profile)
        if not sigma_min < sigma_max:
            raise cfgx.ConfigKeyError(f"config.yaml: '{spec_path}' needs fwhm_min < fwhm_max")

        resolved[key] = PLComponentSpec(
            key=key,
            label=cfgx.text(spec, "label", spec_path),
            profile=profile,
            center_init=float(np.clip(center_init, center_min, center_max)),
            center_min=center_min,
            center_max=center_max,
            sigma_init=float(np.clip(sigma_init, sigma_min, sigma_max)),
            sigma_min=sigma_min,
            sigma_max=sigma_max,
            height_scale=max(cfgx.number(spec, "height_scale", spec_path), 0.0),
            # Optional constraints; absent means "no extra constraint", not a hidden scientific value.
            amplitude_min=max(float(spec.get("amplitude_min", 0.0)), 0.0),
            fraction_init=float(np.clip(cfgx.number(spec, "fraction_init", spec_path), 0.0, 1.0)),
            vary_center=bool(spec.get("vary_center", True)),
            vary_sigma=bool(spec.get("vary_sigma", True)),
            vary_amplitude=bool(spec.get("vary_amplitude", True)),
            vary_fraction=bool(spec.get("vary_fraction", True)),
        )
    if not resolved:
        raise cfgx.ConfigKeyError(f"config.yaml: '{path}' must define at least one component")
    return resolved


def _resolve_pl_model_components(
    raw: Mapping[str, Any],
    models: Sequence[str],
    components: Mapping[str, PLComponentSpec],
    path: str,
) -> dict[str, list[str]]:
    resolved: dict[str, list[str]] = {}
    for model_name in models:
        keys = [_pl_component_key(item) for item in cfgx.string_list(raw, model_name, path) if item]
        unknown = [key for key in keys if key not in components]
        if not keys or unknown:
            raise cfgx.ConfigKeyError(
                f"config.yaml: '{path}.{model_name}' must list components defined in pl.fit.components"
                f" (unknown: {unknown or 'none listed'})"
            )
        resolved[model_name] = keys
    return resolved


def _resolve_prefit_config(raw: Mapping[str, Any], path: str) -> PreFitConfig:
    noise = cfgx.section(raw, "noise_windows", path)
    noise_path = f"{path}.noise_windows"
    return PreFitConfig(
        enabled=cfgx.flag(raw, "enabled", path),
        peak_window_half_width=cfgx.number(raw, "peak_window_half_width", path),
        e2g_snr_hard_min=cfgx.number(raw, "e2g_snr_hard_min", path),
        e2g_snr_soft_min=cfgx.number(raw, "e2g_snr_soft_min", path),
        a1g_snr_hard_min=cfgx.number(raw, "a1g_snr_hard_min", path),
        a1g_snr_soft_min=cfgx.number(raw, "a1g_snr_soft_min", path),
        noise_left=cfgx.pair(noise, "left", noise_path),
        noise_right=cfgx.pair(noise, "right", noise_path),
        min_points=cfgx.integer(raw, "min_points", path),
        noise_min_points=cfgx.integer(noise, "min_points", noise_path),
        noise_fallback_percentile=cfgx.number(noise, "fallback_percentile", noise_path),
        noise_fallback_min_points=cfgx.integer(noise, "fallback_min_points", noise_path),
        local_baseline_percentile=cfgx.number(raw, "local_baseline_percentile", path),
    )


def _default_baseline_windows_from_roi(
    x_min: float,
    x_max: float,
    edge_fraction: float,
    edge_min: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    span = float(x_max) - float(x_min)
    edge = max(float(edge_min), float(edge_fraction) * span)
    left = (float(x_min), float(x_min + edge))
    right = (float(x_max - edge), float(x_max))
    return left, right


def _resolve_model_windows(raw: Mapping[str, Any], models: Sequence[str], path: str) -> dict[str, NPeakWindowSpec]:
    resolved: dict[str, NPeakWindowSpec] = {}
    for model_name in models:
        spec_path = f"{path}.{model_name}"
        spec = cfgx.section(raw, model_name, path)
        x_min = cfgx.number(spec, "x_min", spec_path)
        x_max = cfgx.number(spec, "x_max", spec_path)
        if not x_min < x_max:
            raise cfgx.ConfigKeyError(f"config.yaml: '{spec_path}' needs x_min < x_max")
        resolved[model_name] = NPeakWindowSpec(
            x_min=x_min,
            x_max=x_max,
            left_base=cfgx.pair(spec, "left_base", spec_path),
            right_base=cfgx.pair(spec, "right_base", spec_path),
        )
    return resolved


def _resolve_sigma_bounds_by_peak(raw: Mapping[str, Any], path: str) -> dict[str, tuple[float, float]]:
    resolved: dict[str, tuple[float, float]] = {}
    for label in RAMAN_PEAK_LABELS["peak_5_model"]:
        key = label.lower()
        lo, hi = cfgx.pair(raw, key, path)
        if not lo < hi:
            raise cfgx.ConfigKeyError(f"config.yaml: '{path}.{key}' needs [min, max] with min < max")
        resolved[key] = (lo, hi)
    return resolved


def _require_known_raman_models(models: Sequence[str], path: str) -> None:
    unknown = [name for name in models if name not in RAMAN_PEAK_MODELS]
    if unknown:
        raise cfgx.ConfigKeyError(f"config.yaml: '{path}' has unsupported Raman models {unknown}")


def _sigma_bounds_for_peak(cfg: RamanFitConfig, peak_label: str) -> tuple[float, float]:
    return cfg.sigma_bounds_by_peak[str(peak_label).lower()]


def _height_to_area_factor(sigma: float, fraction: float) -> float:
    sigma_val = max(float(sigma), 1.0e-12)
    frac = float(np.clip(fraction, 0.0, 1.0))
    sigma_g = sigma_val / np.sqrt(2.0 * np.log(2.0))
    gaussian_height = 1.0 / max(sigma_g * np.sqrt(2.0 * np.pi), 1.0e-12)
    lorentz_height = 1.0 / max(np.pi * sigma_val, 1.0e-12)
    return (1.0 - frac) * gaussian_height + frac * lorentz_height


def _height_guess_to_lmfit_area(height_guess: float, sigma_guess: float, fraction_guess: float) -> float:
    height_to_area_factor = _height_to_area_factor(sigma=sigma_guess, fraction=fraction_guess)
    return float(height_guess) / max(height_to_area_factor, 1.0e-12)


def _estimate_linear_baseline_edges(
    x: np.ndarray,
    y: np.ndarray,
    left_base: tuple[float, float],
    right_base: tuple[float, float],
) -> tuple[float, float]:
    left_mask = (x >= left_base[0]) & (x <= left_base[1])
    right_mask = (x >= right_base[0]) & (x <= right_base[1])
    mask = left_mask | right_mask
    if int(np.sum(mask)) < 4:
        # fallback: line through first/last points
        x0, x1 = float(x[0]), float(x[-1])
        y0, y1 = float(y[0]), float(y[-1])
        slope = (y1 - y0) / max(x1 - x0, 1e-9)
        intercept = y0 - slope * x0
        return slope, intercept

    coeff = np.polyfit(x[mask], y[mask], deg=1)
    return float(coeff[0]), float(coeff[1])


def _bg_slope_bounds(
    baseline_slope: float,
    min_half_width: float,
    multiplier: float,
) -> dict[str, float]:
    """Slope search range centred on the edge estimate so steep backgrounds are not clamped."""
    half_width = max(float(min_half_width), float(multiplier) * abs(baseline_slope))
    return {"min": baseline_slope - half_width, "max": baseline_slope + half_width}


def _noise_std_from_windows(
    x: np.ndarray,
    y: np.ndarray,
    prefit: PreFitConfig,
) -> float:
    left_window, right_window = prefit.noise_left, prefit.noise_right
    left_mask = (x >= left_window[0]) & (x <= left_window[1])
    right_mask = (x >= right_window[0]) & (x <= right_window[1])
    noise_mask = left_mask | right_mask
    noise = y[noise_mask]
    if noise.size < prefit.noise_min_points:
        # Too few points in the noise windows: use the lowest part of the spectrum instead.
        low = float(np.percentile(y, prefit.noise_fallback_percentile))
        noise = y[y <= low]
    if noise.size < prefit.noise_fallback_min_points:
        noise = y
    sigma = float(np.std(noise))
    return max(sigma, 1.0e-6)


def _window_peak_height(
    x: np.ndarray,
    y: np.ndarray,
    center: float,
    half_width: float,
    baseline_percentile: float,
) -> tuple[float, float]:
    mask = (x >= (center - half_width)) & (x <= (center + half_width))
    if int(np.sum(mask)) < 3:
        return 0.0, float(center)
    yw = y[mask]
    xw = x[mask]
    peak_idx = int(np.argmax(yw))
    baseline_local = float(np.percentile(yw, baseline_percentile))
    prominence = float(max(yw[peak_idx] - baseline_local, 0.0))
    return prominence, float(xw[peak_idx])


def _build_n_peak_spec(model_name: str, cfg: RamanFitConfig) -> NPeakSpec:
    labels = RAMAN_PEAK_LABELS.get(model_name)
    if labels is None:
        raise ValueError(f"Unsupported n-peak model: {model_name}")
    center_by_label = {
        "LO": cfg.e2g_init + cfg.lo_offset_from_e2g,
        "E2g": cfg.e2g_init,
        "A1g": cfg.a1g_init,
        "ZO": cfg.a1g_init + cfg.zo_offset_from_a1g,
        "LA": cfg.a1g_init + cfg.la_offset_from_a1g,
    }
    window = cfg.model_windows[model_name]
    return NPeakSpec(
        model_name=model_name,
        peak_labels=list(labels),
        center_guesses=[center_by_label[label] for label in labels],
        width_guesses=[cfg.sigma_init_by_peak[label.lower()] for label in labels],
        height_scales=list(cfg.height_scales[model_name]),
        x_min=window.x_min,
        x_max=window.x_max,
        left_base=window.left_base,
        right_base=window.right_base,
        # E2g/A1g use their own bounds; the tolerance only applies to LO/ZO/LA (absent in peak_2_model).
        center_tolerance=cfg.center_tolerance_by_model.get(model_name, float("nan")),
        lock_baseline=cfg.lock_baseline_by_model[model_name],
    )


class LmfitRamanModelEnsembleFitting(ModelEnsembleFittingStage):
    """
    Raman/PL ensemble fitter using multiple candidate models.

    Model lists and every fit setting come from config.yaml (`raman.models` / `raman.fit`,
    `pl.models` / `pl.fit`).
    - Raman models: peak_2_model, peak_3_model, peak_4_model, peak_5_model
    - PL models: any name listed in `pl.fit.model_components`
    """

    def __init__(self, enable_pl: bool = True) -> None:
        self.enable_pl = bool(enable_pl)

    def _resolve_fit_config(self, context: PipelineContext, modality: str) -> RamanFitConfig:
        config = context.config if isinstance(context.config, Mapping) else {}
        if modality == "pl":
            return self._resolve_pl_fit_config(cfgx.section(config, "pl", ""))
        return self._resolve_raman_fit_config(cfgx.section(config, "raman", ""))

    @staticmethod
    def _resolve_raman_fit_config(section: Mapping[str, Any]) -> RamanFitConfig:
        p = "raman.fit"
        fit = cfgx.section(section, "fit", "raman")
        models = _resolve_models(section, "raman")
        _require_known_raman_models(models, "raman.models")

        anchor = cfgx.section(fit, "two_stage_anchor", p)
        refine = cfgx.section(fit, "auto_refine", p)
        baseline = cfgx.section(fit, "baseline", p)
        slope = cfgx.section(baseline, "slope_bounds", f"{p}.baseline")
        lock = cfgx.section(baseline, "lock_by_model", f"{p}.baseline")
        heights = cfgx.section(fit, "height_scales", p)
        tolerances = cfgx.section(fit, "center_tolerance_by_model", p)
        sigma_init = cfgx.section(fit, "sigma_init_by_peak", p)
        offsets = cfgx.section(fit, "offset_bounds", p)

        offset_bounds = {
            name: {item: cfgx.number(cfgx.section(offsets, name, f"{p}.offset_bounds"), item, f"{p}.offset_bounds.{name}")
                   for item in items}
            for name, items in _OFFSET_BOUND_KEYS.items()
        }
        height_scales: dict[str, list[float]] = {}
        center_tolerance_by_model: dict[str, float] = {}
        lock_baseline_by_model: dict[str, bool] = {}
        for model_name in models:
            n_peaks = len(RAMAN_PEAK_LABELS[model_name])
            height_scales[model_name] = cfgx.number_list(heights, model_name, f"{p}.height_scales", length=n_peaks)
            lock_baseline_by_model[model_name] = cfgx.flag(lock, model_name, f"{p}.baseline.lock_by_model")
            if model_name != "peak_2_model":
                center_tolerance_by_model[model_name] = cfgx.number(
                    tolerances, model_name, f"{p}.center_tolerance_by_model"
                )

        return RamanFitConfig(
            models=models,
            x_min=cfgx.number(fit, "x_min", p),
            x_max=cfgx.number(fit, "x_max", p),
            e2g_init=cfgx.number(fit, "e2g_init", p),
            a1g_init=cfgx.number(fit, "a1g_init", p),
            lo_offset_from_e2g=cfgx.number(fit, "lo_offset_from_e2g", p),
            zo_offset_from_a1g=cfgx.number(fit, "zo_offset_from_a1g", p),
            la_offset_from_a1g=cfgx.number(fit, "la_offset_from_a1g", p),
            height_scales=height_scales,
            center_tolerance_by_model=center_tolerance_by_model,
            e2g_bounds=(cfgx.number(fit, "e2g_min", p), cfgx.number(fit, "e2g_max", p)),
            a1g_bounds=(cfgx.number(fit, "a1g_min", p), cfgx.number(fit, "a1g_max", p)),
            sigma_bounds_by_peak=_resolve_sigma_bounds_by_peak(cfgx.section(fit, "sigma_bounds_by_peak", p), f"{p}.sigma_bounds_by_peak"),
            compare_x_min=cfgx.number(fit, "compare_x_min", p),
            compare_x_max=cfgx.number(fit, "compare_x_max", p),
            enforce_peak_order=cfgx.flag(fit, "enforce_peak_order", p),
            two_stage_anchor_enabled=cfgx.flag(anchor, "enabled", f"{p}.two_stage_anchor"),
            two_stage_anchor_window=max(cfgx.number(anchor, "window", f"{p}.two_stage_anchor"), 0.0),
            auto_refine_enabled=cfgx.flag(refine, "enabled", f"{p}.auto_refine"),
            auto_refine_min_rmse_improvement=max(cfgx.number(refine, "min_rmse_improvement", f"{p}.auto_refine"), 0.0),
            prefit=_resolve_prefit_config(cfgx.section(fit, "prefit", p), f"{p}.prefit"),
            model_windows=_resolve_model_windows(cfgx.section(fit, "model_windows", p), models, f"{p}.model_windows"),
            pl_components={},
            pl_model_components={},
            pl_a_minus_a0_split=(False, float("nan"), float("nan"), float("nan")),
            pl_trion_exciton_fwhm_ratio=(False, float("nan"), float("nan"), float("nan")),
            pl_share_exciton_fraction=False,
            pl_spike_residual_sigma_k=float("nan"),
            pl_spike_span_ratio=float("nan"),
            pl_spike_span_percentiles=(float("nan"), float("nan")),
            sigma_init_by_peak={
                label.lower(): cfgx.number(sigma_init, label.lower(), f"{p}.sigma_init_by_peak")
                for label in RAMAN_PEAK_LABELS["peak_5_model"]
            },
            fraction_init=float(np.clip(cfgx.number(fit, "fraction_init", p), 0.0, 1.0)),
            lock_baseline_by_model=lock_baseline_by_model,
            locked_baseline_rel_tol=cfgx.number(baseline, "locked_rel_tol", f"{p}.baseline"),
            bg_slope_min_half_width=cfgx.number(slope, "min_half_width", f"{p}.baseline.slope_bounds"),
            bg_slope_multiplier=cfgx.number(slope, "slope_multiplier", f"{p}.baseline.slope_bounds"),
            manual_refit_bg_slope_bound=cfgx.number(baseline, "manual_refit_slope_bound", f"{p}.baseline"),
            # Raman baseline windows always come from model_windows.
            baseline_edge_fraction=float("nan"),
            baseline_edge_min=float("nan"),
            anchor_fallback_half_window=cfgx.number(anchor, "fallback_half_window", f"{p}.two_stage_anchor"),
            offset_bounds=offset_bounds,
            min_roi_points=cfgx.integer(fit, "min_roi_points", p),
            min_spectrum_points=cfgx.integer(fit, "min_spectrum_points", p),
            pl_seed_baseline_percentile=float("nan"),
            pl_seed_local_baseline_percentile=float("nan"),
            pl_seed_local_half_width_min=float("nan"),
            pl_amplitude_floor_fraction=float("nan"),
        )

    @staticmethod
    def _resolve_pl_fit_config(section: Mapping[str, Any]) -> RamanFitConfig:
        p = "pl.fit"
        fit = cfgx.section(section, "fit", "pl")
        models = _resolve_models(section, "pl")
        split = cfgx.section(fit, "a_minus_a0_split", p)
        ratio = cfgx.section(fit, "trion_exciton_fwhm_ratio", p)
        spike = cfgx.section(fit, "spike_check", p)
        seed = cfgx.section(fit, "seed", p)
        baseline = cfgx.section(fit, "baseline", p)
        components = _resolve_pl_components(cfgx.section(fit, "components", p), f"{p}.components")
        model_components = _resolve_pl_model_components(
            cfgx.section(fit, "model_components", p), models, components, f"{p}.model_components"
        )
        nan = float("nan")
        return RamanFitConfig(
            models=models,
            x_min=cfgx.number(fit, "x_min", p),
            x_max=cfgx.number(fit, "x_max", p),
            # Raman peak-model fields: not used by PL component fits.
            e2g_init=nan,
            a1g_init=nan,
            lo_offset_from_e2g=nan,
            zo_offset_from_a1g=nan,
            la_offset_from_a1g=nan,
            height_scales={},
            center_tolerance_by_model={},
            e2g_bounds=(nan, nan),
            a1g_bounds=(nan, nan),
            sigma_bounds_by_peak={},
            compare_x_min=cfgx.number(fit, "compare_x_min", p),
            compare_x_max=cfgx.number(fit, "compare_x_max", p),
            enforce_peak_order=False,
            two_stage_anchor_enabled=False,
            two_stage_anchor_window=nan,
            auto_refine_enabled=False,
            auto_refine_min_rmse_improvement=nan,
            prefit=PreFitConfig.disabled(),
            model_windows={},
            pl_components=components,
            pl_model_components=model_components,
            pl_a_minus_a0_split=(
                cfgx.flag(split, "enabled", f"{p}.a_minus_a0_split"),
                cfgx.number(split, "min", f"{p}.a_minus_a0_split"),
                cfgx.number(split, "max", f"{p}.a_minus_a0_split"),
                cfgx.number(split, "init", f"{p}.a_minus_a0_split"),
            ),
            pl_trion_exciton_fwhm_ratio=(
                cfgx.flag(ratio, "enabled", f"{p}.trion_exciton_fwhm_ratio"),
                cfgx.number(ratio, "min", f"{p}.trion_exciton_fwhm_ratio"),
                cfgx.number(ratio, "max", f"{p}.trion_exciton_fwhm_ratio"),
                cfgx.number(ratio, "init", f"{p}.trion_exciton_fwhm_ratio"),
            ),
            pl_share_exciton_fraction=cfgx.flag(fit, "share_exciton_fraction", p),
            pl_spike_residual_sigma_k=cfgx.number(spike, "residual_sigma_k", f"{p}.spike_check"),
            pl_spike_span_ratio=cfgx.number(spike, "span_ratio", f"{p}.spike_check"),
            pl_spike_span_percentiles=cfgx.pair(spike, "span_percentiles", f"{p}.spike_check"),
            sigma_init_by_peak={},
            fraction_init=nan,
            lock_baseline_by_model={},
            locked_baseline_rel_tol=nan,
            bg_slope_min_half_width=nan,
            bg_slope_multiplier=nan,
            manual_refit_bg_slope_bound=nan,
            baseline_edge_fraction=cfgx.number(baseline, "default_edge_fraction", f"{p}.baseline"),
            baseline_edge_min=cfgx.number(baseline, "default_edge_min", f"{p}.baseline"),
            anchor_fallback_half_window=nan,
            offset_bounds={},
            min_roi_points=cfgx.integer(fit, "min_roi_points", p),
            min_spectrum_points=cfgx.integer(fit, "min_spectrum_points", p),
            pl_seed_baseline_percentile=cfgx.number(seed, "baseline_percentile", f"{p}.seed"),
            pl_seed_local_baseline_percentile=cfgx.number(seed, "local_baseline_percentile", f"{p}.seed"),
            pl_seed_local_half_width_min=cfgx.number(seed, "local_half_width_min", f"{p}.seed"),
            pl_amplitude_floor_fraction=cfgx.number(seed, "amplitude_floor_fraction", f"{p}.seed"),
        )

    @staticmethod
    def _normalize_reasons(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def _evaluate_prefit_gate(
        self,
        x_full: np.ndarray,
        y_corr: np.ndarray,
        cfg: RamanFitConfig,
    ) -> PreFitEvaluation:
        prefit = cfg.prefit
        if not prefit.enabled:
            return PreFitEvaluation(
                status="valid",
                invalid_reasons=[],
                attention_reasons=[],
                metrics={
                    "prefit_noise_std": 0.0,
                    "prefit_e2g_peak_height": 0.0,
                    "prefit_a1g_peak_height": 0.0,
                    "prefit_e2g_snr": 0.0,
                    "prefit_a1g_snr": 0.0,
                },
            )

        noise_std = _noise_std_from_windows(x_full, y_corr, prefit)
        e2g_height, e2g_peak_x = _window_peak_height(
            x_full,
            y_corr,
            center=cfg.e2g_init,
            half_width=prefit.peak_window_half_width,
            baseline_percentile=prefit.local_baseline_percentile,
        )
        a1g_height, a1g_peak_x = _window_peak_height(
            x_full,
            y_corr,
            center=cfg.a1g_init,
            half_width=prefit.peak_window_half_width,
            baseline_percentile=prefit.local_baseline_percentile,
        )
        e2g_snr = e2g_height / max(noise_std, 1.0e-6)
        a1g_snr = a1g_height / max(noise_std, 1.0e-6)

        invalid_reasons: list[str] = []
        attention_reasons: list[str] = []
        # Weak E2g is common in pristine/thick regions: still fit it, but flag attention.
        if e2g_snr < prefit.e2g_snr_hard_min:
            attention_reasons.append("prefit_e2g_snr_below_hard")
        elif e2g_snr < prefit.e2g_snr_soft_min:
            attention_reasons.append("prefit_e2g_snr_below_soft")
        if a1g_snr < prefit.a1g_snr_hard_min:
            invalid_reasons.append("prefit_a1g_snr_below_hard")
        elif a1g_snr < prefit.a1g_snr_soft_min:
            attention_reasons.append("prefit_a1g_snr_below_soft")

        status = "invalid" if invalid_reasons else ("attention" if attention_reasons else "valid")
        return PreFitEvaluation(
            status=status,
            invalid_reasons=invalid_reasons,
            attention_reasons=attention_reasons,
            metrics={
                "prefit_noise_std": float(noise_std),
                "prefit_e2g_peak_height": float(e2g_height),
                "prefit_a1g_peak_height": float(a1g_height),
                "prefit_e2g_peak_x": float(e2g_peak_x),
                "prefit_a1g_peak_x": float(a1g_peak_x),
                "prefit_e2g_snr": float(e2g_snr),
                "prefit_a1g_snr": float(a1g_snr),
            },
        )

    def _candidate_math_invalid_reasons(self, candidate: FitCandidate) -> list[str]:
        reasons: list[str] = []
        y_pred = np.asarray(candidate.fitted_y, dtype=float)
        if y_pred.size == 0 or not np.all(np.isfinite(y_pred)):
            reasons.append("invalid_fitted_y_non_finite")

        for metric_key in ("rmse", "aic", "bic"):
            metric_value = _finite(candidate.metrics.get(metric_key), default=float("nan"))
            if not np.isfinite(metric_value):
                reasons.append(f"invalid_metric_{metric_key}_non_finite")

        peak_names = {
            str(key[: -len("_fwhm")])
            for key in candidate.params
            if isinstance(key, str) and key.endswith("_fwhm")
        }
        peak_names.update(
            str(key[: -len("_area")])
            for key in candidate.params
            if isinstance(key, str) and key.endswith("_area")
        )
        for peak_name in sorted(peak_names):
            fwhm_value = candidate.params.get(f"{peak_name}_fwhm")
            area_value = candidate.params.get(f"{peak_name}_area")

            if fwhm_value is not None:
                fwhm = _finite(fwhm_value, default=float("nan"))
                if not np.isfinite(fwhm):
                    reasons.append(f"{peak_name}_fwhm_non_finite")
                elif fwhm <= 0.0:
                    reasons.append(f"{peak_name}_fwhm_non_positive")

            if area_value is not None:
                area = _finite(area_value, default=float("nan"))
                if not np.isfinite(area):
                    reasons.append(f"{peak_name}_area_non_finite")
                elif area < 0.0:
                    reasons.append(f"{peak_name}_area_negative")

        # de-duplicate while preserving order
        return list(dict.fromkeys(reasons))

    def _apply_candidate_status(
        self,
        candidate: FitCandidate,
        prefit_eval: PreFitEvaluation,
        fit_invalid_reasons: list[str] | None = None,
    ) -> FitCandidate:
        invalid_reasons = list(prefit_eval.invalid_reasons)
        if fit_invalid_reasons:
            invalid_reasons.extend(fit_invalid_reasons)
        invalid_reasons = list(dict.fromkeys(invalid_reasons))
        attention_reasons = list(prefit_eval.attention_reasons)
        candidate_attention = candidate.params.get("attention_reasons")
        if isinstance(candidate_attention, list):
            attention_reasons.extend(str(item) for item in candidate_attention if str(item).strip())
        elif isinstance(candidate_attention, str) and candidate_attention.strip():
            attention_reasons.append(candidate_attention.strip())
        attention_reasons = list(dict.fromkeys(attention_reasons))

        if invalid_reasons:
            fit_status = "invalid"
        elif attention_reasons:
            fit_status = "attention"
        else:
            fit_status = "valid"

        params_out = dict(candidate.params)
        params_out["fit_status"] = fit_status
        params_out["invalid_reasons"] = invalid_reasons
        params_out["attention_reasons"] = attention_reasons

        metrics_out = dict(candidate.metrics)
        metrics_out["is_valid_candidate"] = 0.0 if invalid_reasons else 1.0
        metrics_out.update(prefit_eval.metrics)
        metrics_out["prefit_pass"] = 0.0 if prefit_eval.status == "invalid" else 1.0

        return FitCandidate(
            model_name=candidate.model_name,
            params=params_out,
            fitted_y=list(candidate.fitted_y),
            metrics=metrics_out,
        )

    @staticmethod
    def _fallback_candidate(
        model_name: str,
        x_full: np.ndarray,
        y_corr: np.ndarray,
        fit_status: str = "invalid",
        invalid_reasons: list[str] | None = None,
        attention_reasons: list[str] | None = None,
        extra_metrics: Mapping[str, float] | None = None,
    ) -> FitCandidate:
        peak_idx = int(np.argmax(y_corr))
        peak_x = float(x_full[peak_idx])
        peak_amp = float(y_corr[peak_idx])
        mean_y = float(np.mean(y_corr))
        rmse = float(np.sqrt(np.mean((y_corr - mean_y) ** 2)))

        return FitCandidate(
            model_name=model_name,
            params={
                "peak_position": peak_x,
                "peak_amplitude": peak_amp,
                "e2g_position": peak_x,
                "a1g_position": peak_x,
                "delta_e2g_a1g": 0.0,
                "bg_slope": 0.0,
                "bg_intercept": mean_y,
                "fit_status": fit_status,
                "invalid_reasons": list(invalid_reasons or []),
                "attention_reasons": list(attention_reasons or []),
            },
            fitted_y=[mean_y] * len(x_full),
            metrics={
                # Sentinel scores so fallback rows always rank after real fits; not a physical value.
                "aic": rmse + 100.0,
                "bic": rmse + 101.0,
                "rmse": rmse,
                "r2": 0.0,
                "is_valid_candidate": 0.0 if fit_status == "invalid" else 1.0,
                **(dict(extra_metrics or {})),
            },
        )

    def _fit_pl_model(
        self,
        model_name: str,
        x_full: np.ndarray,
        y_corr: np.ndarray,
        cfg: RamanFitConfig,
    ) -> FitCandidate:
        component_keys = cfg.pl_model_components.get(model_name)
        if not component_keys:
            raise ValueError(f"PL model {model_name} is not defined in pl.fit.model_components")
        return self._fit_pl_component_model(
            model_name=model_name,
            component_keys=component_keys,
            x_full=x_full,
            y_corr=y_corr,
            cfg=cfg,
        )

    def _fit_pl_component_model(
        self,
        model_name: str,
        component_keys: Sequence[str],
        x_full: np.ndarray,
        y_corr: np.ndarray,
        cfg: RamanFitConfig,
    ) -> FitCandidate:
        mask = self._mask_roi(x_full, cfg.x_min, cfg.x_max)
        x_fit = x_full[mask]
        y_fit = y_corr[mask]
        if x_fit.size < cfg.min_roi_points:
            raise ValueError(f"Insufficient ROI points for PL model {model_name}")

        selected_components: list[PLComponentSpec] = []
        for key in component_keys:
            spec = cfg.pl_components.get(_pl_component_key(key))
            if spec is not None:
                selected_components.append(spec)
        if not selected_components:
            raise ValueError(f"No configured PL components for model {model_name}")

        model = LinearModel(prefix="bg_")
        for spec in selected_components:
            prefix = f"{spec.key}_"
            if spec.profile == "gaussian":
                model = model + GaussianModel(prefix=prefix)
            else:
                model = model + PseudoVoigtModel(prefix=prefix)

        params = model.make_params()
        left_base, right_base = _default_baseline_windows_from_roi(
            cfg.x_min, cfg.x_max, cfg.baseline_edge_fraction, cfg.baseline_edge_min
        )
        baseline_slope, baseline_intercept = _estimate_linear_baseline_edges(
            x_fit, y_fit, left_base, right_base
        )
        params["bg_slope"].set(value=baseline_slope)
        params["bg_intercept"].set(value=baseline_intercept)

        y_low = float(np.percentile(y_fit, cfg.pl_seed_baseline_percentile))
        dynamic_height = max(float(np.max(y_fit) - y_low), 1.0e-6)
        for spec in selected_components:
            prefix = f"{spec.key}_"
            local_half_width = max(
                float(spec.center_init - spec.center_min),
                float(spec.center_max - spec.center_init),
                cfg.pl_seed_local_half_width_min,
            )
            local_height, local_center = _window_peak_height(
                x_fit,
                y_fit,
                center=spec.center_init,
                half_width=local_half_width,
                baseline_percentile=cfg.pl_seed_local_baseline_percentile,
            )
            height_guess = max(local_height, dynamic_height * spec.height_scale, 1.0e-6)
            center_guess = float(np.clip(local_center, spec.center_min, spec.center_max))
            sigma_guess = float(np.clip(spec.sigma_init, spec.sigma_min, spec.sigma_max))
            fraction_guess = float(np.clip(spec.fraction_init, 0.0, 1.0))
            area_guess_lmfit = _height_guess_to_lmfit_area(
                height_guess=height_guess,
                sigma_guess=sigma_guess,
                fraction_guess=fraction_guess,
            )

            amplitude_floor = max(spec.amplitude_min, area_guess_lmfit * cfg.pl_amplitude_floor_fraction, 1.0e-3)
            params[f"{prefix}center"].set(
                value=center_guess,
                min=spec.center_min,
                max=spec.center_max,
                vary=spec.vary_center,
            )
            params[f"{prefix}sigma"].set(
                value=sigma_guess,
                min=spec.sigma_min,
                max=spec.sigma_max,
                vary=spec.vary_sigma,
            )
            params[f"{prefix}amplitude"].set(
                value=max(area_guess_lmfit, amplitude_floor),
                min=amplitude_floor,
                vary=spec.vary_amplitude,
            )
            if f"{prefix}fraction" in params:
                params[f"{prefix}fraction"].set(
                    value=fraction_guess,
                    min=0.0,
                    max=1.0,
                    vary=spec.vary_fraction,
                )

        has_a_minus = any(s.key == "a_minus" for s in selected_components)
        has_a0 = any(s.key == "a0" for s in selected_components)

        if has_a_minus and has_a0:
            split_enabled, split_min, split_max, split_init = cfg.pl_a_minus_a0_split
            if split_enabled and "a0_center" in params and "a_minus_center" in params:
                params.add("d_a0_from_a_minus", value=split_init, min=split_min, max=split_max, vary=True)
                params["a0_center"].set(expr="a_minus_center + d_a0_from_a_minus")

            ratio_enabled, ratio_min, ratio_max, ratio_init = cfg.pl_trion_exciton_fwhm_ratio
            if ratio_enabled and "a_minus_sigma" in params and "a0_sigma" in params:
                params.add("ratio_trion_sigma", value=ratio_init, min=ratio_min, max=ratio_max, vary=True)
                params["a_minus_sigma"].set(expr="a0_sigma * ratio_trion_sigma")

            if cfg.pl_share_exciton_fraction:
                if "a0_fraction" in params and "a_minus_fraction" in params:
                    params["a0_fraction"].set(expr="a_minus_fraction")

        fit_result = model.fit(y_fit, params, x=x_fit, nan_policy="omit")
        y_pred_full = model.eval(fit_result.params, x=x_full)
        peak_labels = [spec.key for spec in selected_components]
        return self._candidate_from_result(
            model_name=model_name,
            fit_result=fit_result,
            x_fit=x_fit,
            y_fit=y_fit,
            x_full=x_full,
            y_pred_full=np.asarray(y_pred_full, dtype=float),
            peak_labels=peak_labels,
            prefix_for_label={spec.key: f"{spec.key}_" for spec in selected_components},
            profile_for_label={spec.key: spec.profile for spec in selected_components},
            spike_residual_sigma_k=cfg.pl_spike_residual_sigma_k,
            spike_span_ratio=cfg.pl_spike_span_ratio,
            spike_span_percentiles=cfg.pl_spike_span_percentiles,
        )

    def _mask_roi(self, x_full: np.ndarray, x_min: float, x_max: float) -> np.ndarray:
        return (x_full >= x_min) & (x_full <= x_max)

    @staticmethod
    def _fit_quality(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float]:
        rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
        ss_res = float(np.sum((y_true - y_pred) ** 2))
        ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
        r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0
        return rmse, r2

    @staticmethod
    def _recompute_metrics_on_window(
        candidate: FitCandidate,
        x_full: np.ndarray,
        y_true: np.ndarray,
        x_min: float,
        x_max: float,
    ) -> None:
        y_pred = np.asarray(candidate.fitted_y, dtype=float)
        if y_pred.size != y_true.size:
            return

        mask = (x_full >= x_min) & (x_full <= x_max)
        if int(np.sum(mask)) < 10:
            mask = np.ones_like(x_full, dtype=bool)

        yt = y_true[mask]
        yp = y_pred[mask]
        resid = yt - yp
        n = int(yt.size)
        if n <= 1:
            return

        rss = float(np.sum(resid**2))
        mse = max(rss / n, 1.0e-12)
        rmse = float(np.sqrt(mse))

        k = int(_finite(candidate.metrics.get("n_params", 1.0), 1.0))
        aic = float(n * np.log(mse) + 2.0 * k)
        bic = float(n * np.log(mse) + k * np.log(max(n, 2)))
        ss_tot = float(np.sum((yt - np.mean(yt)) ** 2))
        r2 = float(1.0 - rss / ss_tot) if ss_tot > 0 else 0.0

        candidate.metrics["aic"] = aic
        candidate.metrics["bic"] = bic
        candidate.metrics["rmse"] = rmse
        candidate.metrics["r2"] = r2
        candidate.metrics["comparison_n"] = float(n)

    @staticmethod
    def _serialize_candidate(candidate: FitCandidate, include_fitted_y: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model_name": candidate.model_name,
            "params": dict(candidate.params),
            "metrics": dict(candidate.metrics),
        }
        if include_fitted_y:
            payload["fitted_y"] = list(candidate.fitted_y)
        return payload

    def _candidate_from_result(
        self,
        model_name: str,
        fit_result: ModelResult,
        x_fit: np.ndarray,
        y_fit: np.ndarray,
        x_full: np.ndarray,
        y_pred_full: np.ndarray,
        peak_labels: Sequence[str],
        prefix_for_label: Mapping[str, str],
        profile_for_label: Mapping[str, str] | None = None,
        spike_residual_sigma_k: float = float("nan"),
        spike_span_ratio: float = float("nan"),
        spike_span_percentiles: tuple[float, float] = (float("nan"), float("nan")),
    ) -> FitCandidate:
        y_best = fit_result.best_fit
        rmse, r2 = self._fit_quality(y_fit, y_best)
        # Only PL component fits pass per-component profiles.
        is_pl_model = profile_for_label is not None

        # Raman peak models are pseudo-Voigt; PL components carry their own profile below.
        if profile_for_label:
            profiles = set(profile_for_label.values())
            line_profile = profiles.pop() if len(profiles) == 1 else "mixed"
        else:
            line_profile = "pvoigt"

        params_out: dict[str, float] = {
            "bg_slope": _safe_param(fit_result.params, "bg_slope"),
            "bg_intercept": _safe_param(fit_result.params, "bg_intercept"),
            "line_profile": line_profile,  # type: ignore[dict-item]
        }

        peak_heights: list[tuple[str, float, float]] = []
        for label in peak_labels:
            key = label.lower()
            prefix = prefix_for_label[label]
            component_profile = (
                str(profile_for_label.get(label, line_profile)).strip().lower()
                if profile_for_label is not None
                else line_profile
            )

            center = _safe_param(fit_result.params, f"{prefix}center")
            fwhm = _safe_param(fit_result.params, f"{prefix}fwhm")
            height = _safe_param(fit_result.params, f"{prefix}height")
            area = _safe_param(fit_result.params, f"{prefix}amplitude")
            sigma = _safe_param(fit_result.params, f"{prefix}sigma")
            fraction = _safe_param(fit_result.params, f"{prefix}fraction", default=0.0)

            params_out[f"{key}_position"] = center
            params_out[f"{key}_fwhm"] = fwhm
            params_out[f"{key}_height"] = height
            params_out[f"{key}_area"] = area
            params_out[f"{key}_sigma"] = sigma
            params_out[f"{key}_fraction"] = fraction
            params_out[f"{key}_line_profile"] = component_profile  # type: ignore[assignment]
            peak_heights.append((label, center, height))

        e2g_pos = params_out.get("e2g_position")
        a1g_pos = params_out.get("a1g_position")
        if e2g_pos is not None and a1g_pos is not None:
            params_out["delta_e2g_a1g"] = float(a1g_pos - e2g_pos)

        if "e2g_position" in params_out:
            params_out["peak_position"] = float(params_out["e2g_position"])
        elif peak_heights:
            params_out["peak_position"] = float(max(peak_heights, key=lambda t: t[2])[1])

        if "e2g_height" in params_out and "a1g_height" in params_out:
            params_out["peak_amplitude"] = float(max(params_out["e2g_height"], params_out["a1g_height"]))
        elif peak_heights:
            params_out["peak_amplitude"] = float(max(h for _, _, h in peak_heights))

        area_a_minus = params_out.get("a_minus_area")
        area_a0 = params_out.get("a0_area")
        area_b = params_out.get("b_area")
        area_i1 = params_out.get("i1_area")
        area_i2 = params_out.get("i2_area")
        pos_a_minus = params_out.get("a_minus_position")
        pos_a0 = params_out.get("a0_position")
        if area_a_minus is not None and area_a0 is not None:
            a_total = float(area_a_minus + area_a0)
            params_out["a_total_area"] = a_total
            if abs(a_total) > 1.0e-12:
                a0_fraction = float(area_a0 / a_total)
                if abs(float(area_a0)) > max(1.0e-12, abs(a_total) * 1.0e-4):
                    params_out["a_minus_a0_area_ratio"] = float(area_a_minus / area_a0)
                params_out["a0_fraction_of_a_total"] = a0_fraction
                if area_b is not None:
                    params_out["b_to_a_total_area_ratio"] = float(area_b / a_total)
                defect_total = float((area_i1 or 0.0) + (area_i2 or 0.0))
                params_out["defect_total_area"] = defect_total
                params_out["defect_to_a_total_area_ratio"] = float(defect_total / a_total)
        if pos_a_minus is not None and pos_a0 is not None:
            params_out["a_minus_a0_energy_split"] = float(pos_a0 - pos_a_minus)

        if peak_heights and "pl_position" not in params_out:
            dominant_label, dominant_center, dominant_height = max(peak_heights, key=lambda t: t[2])
            dominant_key = dominant_label.lower()
            params_out["dominant_component"] = dominant_key  # type: ignore[assignment]
            # pl_* summary keys belong to PL models only; Raman rows keep lo/e2g/a1g/zo/la.
            if is_pl_model:
                params_out["pl_position"] = float(dominant_center)
                params_out["pl_height"] = float(dominant_height)
                for suffix in ("fwhm", "area", "sigma", "fraction"):
                    source_key = f"{dominant_key}_{suffix}"
                    if source_key in params_out:
                        params_out[f"pl_{suffix}"] = params_out[source_key]

        metrics_out = {
            "aic": _finite(fit_result.aic, 1.0e12),
            "bic": _finite(fit_result.bic, 1.0e12),
            "rmse": rmse,
            "r2": r2,
            "aic_fit": _finite(fit_result.aic, 1.0e12),
            "bic_fit": _finite(fit_result.bic, 1.0e12),
            "rmse_fit": rmse,
            "r2_fit": r2,
            "nfev": _finite(fit_result.nfev, 0.0),
            "n_params": _finite(getattr(fit_result, "nvarys", 1), 1.0),
        }

        if is_pl_model:
            residual = np.asarray(y_fit, dtype=float) - np.asarray(y_best, dtype=float)
            if residual.size:
                resid_med = float(np.median(residual))
                resid_mad = float(np.median(np.abs(residual - resid_med)))
                resid_sigma = max(1.4826 * resid_mad, 1.0e-9)
                positive_resid = float(np.max(residual))
                span_lo, span_hi = spike_span_percentiles
                y_span = float(np.percentile(y_fit, span_hi) - np.percentile(y_fit, span_lo))
                spike_threshold = max(
                    spike_residual_sigma_k * resid_sigma,
                    spike_span_ratio * max(y_span, 1.0e-9),
                )
                metrics_out["pl_max_positive_residual"] = positive_resid
                metrics_out["pl_residual_robust_sigma"] = resid_sigma
                if positive_resid > spike_threshold:
                    reasons = params_out.get("attention_reasons")
                    if not isinstance(reasons, list):
                        reasons = []
                    reasons.append("possible_narrow_spike_artifact")
                    params_out["attention_reasons"] = list(dict.fromkeys(str(item) for item in reasons))

        return FitCandidate(
            model_name=model_name,
            params=params_out,
            fitted_y=[float(v) for v in y_pred_full],
            metrics=metrics_out,
        )

    def _fit_n_peak_model(
        self,
        model_name: str,
        x_full: np.ndarray,
        y_corr: np.ndarray,
        cfg: RamanFitConfig,
        anchor_centers: Mapping[str, float] | None = None,
    ) -> FitCandidate:
        spec = _build_n_peak_spec(model_name, cfg)
        mask = self._mask_roi(x_full, spec.x_min, spec.x_max)
        x_fit = x_full[mask]
        y_fit = y_corr[mask]
        if x_fit.size < cfg.min_roi_points:
            raise ValueError(f"Insufficient ROI points for model {model_name}")

        baseline_slope, baseline_intercept = _estimate_linear_baseline_edges(
            x_fit, y_fit, spec.left_base, spec.right_base
        )
        h_guess = max(float(np.max(y_fit) - np.min(y_fit)), 1.0)

        model = LinearModel(prefix="bg_")
        prefix_for_label: dict[str, str] = {}
        for idx, label in enumerate(spec.peak_labels):
            prefix = f"p{idx}_"
            prefix_for_label[label] = prefix
            model += PseudoVoigtModel(prefix=prefix)

        params = model.make_params()
        params["bg_slope"].set(value=baseline_slope)
        params["bg_intercept"].set(value=baseline_intercept)
        if spec.lock_baseline:
            a_eps = max(1.0e-8, abs(baseline_slope) * cfg.locked_baseline_rel_tol)
            b_eps = max(1.0e-8, abs(baseline_intercept) * cfg.locked_baseline_rel_tol)
            params["bg_slope"].set(value=baseline_slope, min=baseline_slope - a_eps, max=baseline_slope + a_eps)
            params["bg_intercept"].set(
                value=baseline_intercept,
                min=baseline_intercept - b_eps,
                max=baseline_intercept + b_eps,
            )
        else:
            params["bg_slope"].set(value=baseline_slope, **_bg_slope_bounds(baseline_slope, cfg.bg_slope_min_half_width, cfg.bg_slope_multiplier))
            params["bg_intercept"].set(value=baseline_intercept)

        anchor_mode = (
            cfg.two_stage_anchor_enabled
            and model_name != "peak_2_model"
            and anchor_centers is not None
        )

        for idx, label in enumerate(spec.peak_labels):
            prefix = prefix_for_label[label]
            center_guess = spec.center_guesses[idx]
            width_guess = spec.width_guesses[idx]
            height_scale = spec.height_scales[idx]
            height_guess_scaled = height_scale * h_guess
            fraction_guess = float(cfg.fraction_init)
            area_guess_lmfit = _height_guess_to_lmfit_area(
                height_guess=height_guess_scaled,
                sigma_guess=width_guess,
                fraction_guess=fraction_guess,
            )

            if label == "E2g":
                center_min, center_max = cfg.e2g_bounds
            elif label == "A1g":
                center_min, center_max = cfg.a1g_bounds
            else:
                center_min = center_guess - spec.center_tolerance
                center_max = center_guess + spec.center_tolerance

            # Two-stage anchor: lock E2g/A1g search around peak_2 fit center (+/- window).
            if (
                cfg.two_stage_anchor_enabled
                and model_name != "peak_2_model"
                and anchor_centers is not None
                and label in {"E2g", "A1g"}
            ):
                anchor_key = label.lower()
                anchor_value = _finite(anchor_centers.get(anchor_key), default=float("nan"))
                if np.isfinite(anchor_value):
                    center_guess = float(anchor_value)
                    center_min = max(center_min, center_guess - cfg.two_stage_anchor_window)
                    center_max = min(center_max, center_guess + cfg.two_stage_anchor_window)
                    if center_max <= center_min:
                        center_min = center_guess - cfg.anchor_fallback_half_window
                        center_max = center_guess + cfg.anchor_fallback_half_window

            anchor_locked = anchor_mode and label in {"E2g", "A1g"}
            center_name = f"{prefix}center"

            # In anchor mode, avoid prev->next chain and use anchor-centric offsets:
            # LO <- E2g, ZO/LA <- A1g. This keeps dependency local to anchor peaks.
            if cfg.enforce_peak_order and anchor_mode:
                if anchor_locked:
                    params[center_name].set(value=center_guess, min=center_min, max=center_max)
                elif label == "LO" and "E2g" in prefix_for_label:
                    delta_name = "d_lo_from_e2g"
                    lo_bounds = cfg.offset_bounds["lo_from_e2g"]
                    delta_guess = max(abs(float(cfg.lo_offset_from_e2g)), lo_bounds["min"])
                    params.add(delta_name, value=delta_guess, min=lo_bounds["min"], max=lo_bounds["max"])
                    params[center_name].set(expr=f"{prefix_for_label['E2g']}center - {delta_name}")
                elif label == "ZO" and "A1g" in prefix_for_label:
                    delta_name = "d_zo_from_a1g"
                    zo_bounds = cfg.offset_bounds["zo_from_a1g"]
                    delta_guess = max(abs(float(cfg.zo_offset_from_a1g)), zo_bounds["min"])
                    delta_max = max(zo_bounds["max_floor"], delta_guess + zo_bounds["max_margin"])
                    params.add(delta_name, value=delta_guess, min=zo_bounds["min"], max=delta_max)
                    params[center_name].set(expr=f"{prefix_for_label['A1g']}center + {delta_name}")
                elif label == "LA" and "A1g" in prefix_for_label:
                    delta_name = "d_la_from_a1g"
                    la_bounds = cfg.offset_bounds["la_from_a1g"]
                    delta_guess = max(abs(float(cfg.la_offset_from_a1g)), la_bounds["min"])
                    delta_max = max(la_bounds["max_floor"], delta_guess + la_bounds["max_margin"])
                    params.add(delta_name, value=delta_guess, min=la_bounds["min"], max=delta_max)
                    params[center_name].set(expr=f"{prefix_for_label['A1g']}center + {delta_name}")
                elif idx == 0:
                    params[center_name].set(value=center_guess, min=center_min, max=center_max)
                else:
                    prev_label = spec.peak_labels[idx - 1]
                    prev_prefix = prefix_for_label[prev_label]
                    prev_guess = spec.center_guesses[idx - 1]
                    chain = cfg.offset_bounds["chain"]
                    delta_guess = max(center_guess - prev_guess, chain["guess_floor"])
                    delta_name = f"d_{prev_label.lower()}_{label.lower()}"
                    params.add(delta_name, value=delta_guess, min=chain["min"], max=chain["max"])
                    params[center_name].set(expr=f"{prev_prefix}center + {delta_name}")
            elif idx == 0 or not cfg.enforce_peak_order or anchor_locked:
                params[center_name].set(value=center_guess, min=center_min, max=center_max)
            else:
                prev_label = spec.peak_labels[idx - 1]
                prev_prefix = prefix_for_label[prev_label]
                prev_guess = spec.center_guesses[idx - 1]
                chain = cfg.offset_bounds["chain"]
                delta_guess = max(center_guess - prev_guess, chain["guess_floor"])
                delta_name = f"d_{prev_label.lower()}_{label.lower()}"
                params.add(delta_name, value=delta_guess, min=chain["min"], max=chain["max"])
                params[center_name].set(expr=f"{prev_prefix}center + {delta_name}")

            sigma_min, sigma_max = _sigma_bounds_for_peak(cfg, label)
            sigma_guess = float(np.clip(width_guess, sigma_min, sigma_max))
            params[f"{prefix}sigma"].set(value=sigma_guess, min=sigma_min, max=sigma_max)
            params[f"{prefix}amplitude"].set(value=max(area_guess_lmfit, 1.0e-6), min=0.0)
            params[f"{prefix}fraction"].set(value=fraction_guess, min=0.0, max=1.0)

        fit_result = model.fit(y_fit, params, x=x_fit, nan_policy="omit")
        y_pred_full = model.eval(fit_result.params, x=x_full)
        return self._candidate_from_result(
            model_name=model_name,
            fit_result=fit_result,
            x_fit=x_fit,
            y_fit=y_fit,
            x_full=x_full,
            y_pred_full=np.asarray(y_pred_full, dtype=float),
            peak_labels=spec.peak_labels,
            prefix_for_label=prefix_for_label,
        )

    def _fit_candidate(
        self,
        model_name: str,
        x_full: np.ndarray,
        y_corr: np.ndarray,
        cfg: RamanFitConfig,
        anchor_centers: Mapping[str, float] | None = None,
        modality: str = "raman",
    ) -> FitCandidate:
        if modality == "pl":
            return self._fit_pl_model(model_name, x_full, y_corr, cfg)

        if model_name in RAMAN_PEAK_MODELS:
            return self._fit_n_peak_model(
                model_name=model_name,
                x_full=x_full,
                y_corr=y_corr,
                cfg=cfg,
                anchor_centers=anchor_centers,
            )
        raise ValueError(f"Unsupported Raman model: {model_name}")

    def _refine_n_peak_candidate_with_initial(
        self,
        *,
        model_name: str,
        x_full: np.ndarray,
        y_corr: np.ndarray,
        cfg: RamanFitConfig,
        initial_params: Mapping[str, Any],
    ) -> FitCandidate:
        """Second-pass relaxed re-fit from first-pass result (y_corr objective)."""
        spec = _build_n_peak_spec(model_name, cfg)
        mask = self._mask_roi(x_full, spec.x_min, spec.x_max)
        x_fit = x_full[mask]
        y_fit = y_corr[mask]
        if x_fit.size < cfg.min_roi_points:
            raise ValueError(f"Insufficient ROI points for model {model_name}")

        baseline_slope, baseline_intercept = _estimate_linear_baseline_edges(
            x_fit, y_fit, spec.left_base, spec.right_base
        )
        h_guess = max(float(np.max(y_fit) - np.min(y_fit)), 1.0)

        model = LinearModel(prefix="bg_")
        prefix_for_label: dict[str, str] = {}
        for idx, label in enumerate(spec.peak_labels):
            prefix = f"p{idx}_"
            prefix_for_label[label] = prefix
            model += PseudoVoigtModel(prefix=prefix)

        params = model.make_params()
        if spec.lock_baseline:
            a_eps = max(1.0e-8, abs(baseline_slope) * cfg.locked_baseline_rel_tol)
            b_eps = max(1.0e-8, abs(baseline_intercept) * cfg.locked_baseline_rel_tol)
            params["bg_slope"].set(value=baseline_slope, min=baseline_slope - a_eps, max=baseline_slope + a_eps)
            params["bg_intercept"].set(
                value=baseline_intercept,
                min=baseline_intercept - b_eps,
                max=baseline_intercept + b_eps,
            )
        else:
            params["bg_slope"].set(value=baseline_slope, **_bg_slope_bounds(baseline_slope, cfg.bg_slope_min_half_width, cfg.bg_slope_multiplier))
            params["bg_intercept"].set(value=baseline_intercept)

        for idx, label in enumerate(spec.peak_labels):
            peak_key = str(label).strip().lower()
            prefix = prefix_for_label[label]

            center_guess = _finite(initial_params.get(f"{peak_key}_position"), spec.center_guesses[idx])
            sigma_guess_raw = _finite(initial_params.get(f"{peak_key}_sigma"), default=float("nan"))
            if np.isfinite(sigma_guess_raw) and sigma_guess_raw > 0.0:
                width_guess = float(sigma_guess_raw)
            else:
                fwhm_guess = _finite(initial_params.get(f"{peak_key}_fwhm"), default=float("nan"))
                width_guess = float(max(fwhm_guess / 2.0, 1.0e-6)) if np.isfinite(fwhm_guess) else float(spec.width_guesses[idx])
            height_guess = _finite(
                initial_params.get(f"{peak_key}_height"),
                spec.height_scales[idx] * h_guess,
            )
            fraction_guess = float(
                np.clip(_finite(initial_params.get(f"{peak_key}_fraction"), cfg.fraction_init), 0.0, 1.0)
            )

            if label == "E2g":
                center_min, center_max = cfg.e2g_bounds
            elif label == "A1g":
                center_min, center_max = cfg.a1g_bounds
            else:
                center_min = float(center_guess - spec.center_tolerance)
                center_max = float(center_guess + spec.center_tolerance)
            center_guess = float(np.clip(center_guess, center_min, center_max))

            sigma_min, sigma_max = _sigma_bounds_for_peak(cfg, label)
            sigma_guess = float(np.clip(width_guess, sigma_min, sigma_max))
            area_guess_lmfit = _height_guess_to_lmfit_area(
                height_guess=height_guess,
                sigma_guess=sigma_guess,
                fraction_guess=fraction_guess,
            )

            params[f"{prefix}center"].set(value=center_guess, min=center_min, max=center_max)
            params[f"{prefix}sigma"].set(value=sigma_guess, min=sigma_min, max=sigma_max)
            params[f"{prefix}amplitude"].set(value=max(area_guess_lmfit, 1.0e-6), min=0.0)
            params[f"{prefix}fraction"].set(value=fraction_guess, min=0.0, max=1.0)

        fit_result = model.fit(y_fit, params, x=x_fit, nan_policy="omit")
        y_pred_full = model.eval(fit_result.params, x=x_full)
        return self._candidate_from_result(
            model_name=model_name,
            fit_result=fit_result,
            x_fit=x_fit,
            y_fit=y_fit,
            x_full=x_full,
            y_pred_full=np.asarray(y_pred_full, dtype=float),
            peak_labels=spec.peak_labels,
            prefix_for_label=prefix_for_label,
        )

    def _maybe_auto_refine_candidate(
        self,
        *,
        candidate: FitCandidate,
        x_full: np.ndarray,
        y_corr: np.ndarray,
        cfg: RamanFitConfig,
    ) -> FitCandidate:
        if not cfg.auto_refine_enabled:
            return candidate
        if candidate.model_name not in {"peak_2_model", "peak_3_model", "peak_4_model", "peak_5_model"}:
            return candidate

        rmse_before = _finite(candidate.metrics.get("rmse"), default=float("nan"))
        if not np.isfinite(rmse_before) or rmse_before <= 0.0:
            return candidate

        refined = self._refine_n_peak_candidate_with_initial(
            model_name=candidate.model_name,
            x_full=x_full,
            y_corr=y_corr,
            cfg=cfg,
            initial_params=candidate.params,
        )
        self._recompute_metrics_on_window(
            refined,
            x_full=x_full,
            y_true=y_corr,
            x_min=cfg.compare_x_min,
            x_max=cfg.compare_x_max,
        )
        rmse_after = _finite(refined.metrics.get("rmse"), default=float("nan"))
        if not np.isfinite(rmse_after):
            return candidate

        improvement = (rmse_before - rmse_after) / max(rmse_before, 1.0e-12)
        if improvement < cfg.auto_refine_min_rmse_improvement:
            return candidate

        params_out = dict(refined.params)
        metrics_out = dict(refined.metrics)
        metrics_out["auto_refine_applied"] = 1.0
        metrics_out["auto_refine_rmse_before"] = float(rmse_before)
        metrics_out["auto_refine_rmse_after"] = float(rmse_after)
        metrics_out["auto_refine_rmse_improvement_ratio"] = float(improvement)
        return FitCandidate(
            model_name=refined.model_name,
            params=params_out,
            fitted_y=list(refined.fitted_y),
            metrics=metrics_out,
        )

    @staticmethod
    def _best_available_status(candidates: Sequence[FitCandidate]) -> str:
        statuses = [
            str(c.params.get("fit_status", "valid")).strip().lower()
            for c in candidates
        ]
        if "valid" in statuses:
            return "valid"
        if "attention" in statuses:
            return "attention"
        return "invalid"

    @staticmethod
    def _resolve_modality(metadata: Mapping[str, Any]) -> str:
        modality = str(metadata.get("modality", "raman")).strip().lower()
        return modality or "raman"

    @staticmethod
    def _default_prefit_evaluation() -> PreFitEvaluation:
        return PreFitEvaluation(
            status="valid",
            invalid_reasons=[],
            attention_reasons=[],
            metrics={
                "prefit_noise_std": 0.0,
                "prefit_e2g_peak_height": 0.0,
                "prefit_a1g_peak_height": 0.0,
                "prefit_e2g_peak_x": 0.0,
                "prefit_a1g_peak_x": 0.0,
                "prefit_e2g_snr": 0.0,
                "prefit_a1g_snr": 0.0,
            },
        )

    def _fit_spectrum(
        self,
        *,
        spectrum: PreprocessedSpectrum,
        baseline_y: Sequence[float],
        cfg: RamanFitConfig,
    ) -> _SpectrumFitResult:
        modality = self._resolve_modality(spectrum.metadata)
        x_full = np.asarray(spectrum.x, dtype=float)
        y_full = np.asarray(spectrum.y, dtype=float)
        baseline = np.asarray(baseline_y, dtype=float)
        y_corr = y_full - baseline

        failures: list[dict[str, str]] = []
        if modality == "raman" and x_full.size >= cfg.prefit.min_points:
            prefit_eval = self._evaluate_prefit_gate(x_full=x_full, y_corr=y_corr, cfg=cfg)
        else:
            prefit_eval = self._default_prefit_evaluation()

        raw_candidates: list[FitCandidate] = []
        if modality == "raman":
            if x_full.size < cfg.min_spectrum_points:
                raw_candidates.append(
                    self._fallback_candidate(
                        model_name="fallback_signal_tracking",
                        x_full=x_full,
                        y_corr=y_corr,
                        fit_status="attention",
                        attention_reasons=["raman_too_few_points"],
                        extra_metrics=prefit_eval.metrics,
                    )
                )
            elif prefit_eval.status == "invalid":
                raw_candidates.append(
                    self._fallback_candidate(
                        model_name="prefit_gate_invalid",
                        x_full=x_full,
                        y_corr=y_corr,
                        fit_status="invalid",
                        invalid_reasons=list(prefit_eval.invalid_reasons),
                        attention_reasons=list(prefit_eval.attention_reasons),
                        extra_metrics=prefit_eval.metrics,
                    )
                )
            else:
                peak2_anchor: FitCandidate | None = None
                if cfg.two_stage_anchor_enabled:
                    try:
                        peak2_anchor = self._fit_n_peak_model(
                            model_name="peak_2_model",
                            x_full=x_full,
                            y_corr=y_corr,
                            cfg=cfg,
                            anchor_centers=None,
                        )
                    except Exception as exc:
                        failures.append(
                            {
                                "spectrum_id": spectrum.spectrum_id,
                                "model_name": "peak_2_model(anchor_stage)",
                                "error": str(exc),
                            }
                        )

                anchor_centers: dict[str, float] | None = None
                if peak2_anchor is not None:
                    anchor_centers = {
                        "e2g": _finite(peak2_anchor.params.get("e2g_position"), float("nan")),
                        "a1g": _finite(peak2_anchor.params.get("a1g_position"), float("nan")),
                    }

                for model_name in cfg.models:
                    try:
                        if model_name == "peak_2_model" and peak2_anchor is not None:
                            raw_candidates.append(peak2_anchor)
                        else:
                            raw_candidates.append(
                                self._fit_candidate(
                                    model_name=model_name,
                                    x_full=x_full,
                                    y_corr=y_corr,
                                    cfg=cfg,
                                    anchor_centers=anchor_centers,
                                    modality="raman",
                                )
                            )
                    except Exception as exc:  # pragma: no cover - defensive fallback
                        failures.append(
                            {
                                "spectrum_id": spectrum.spectrum_id,
                                "model_name": model_name,
                                "error": str(exc),
                            }
                        )
        elif modality == "pl" and self.enable_pl:
            if x_full.size < cfg.min_spectrum_points:
                raw_candidates.append(
                    self._fallback_candidate(
                        model_name="fallback_signal_tracking",
                        x_full=x_full,
                        y_corr=y_corr,
                        fit_status="attention",
                        attention_reasons=["pl_too_few_points"],
                        extra_metrics=prefit_eval.metrics,
                    )
                )
            else:
                for model_name in cfg.models:
                    try:
                        raw_candidates.append(
                            self._fit_candidate(
                                model_name=model_name,
                                x_full=x_full,
                                y_corr=y_corr,
                                cfg=cfg,
                                anchor_centers=None,
                                modality="pl",
                            )
                        )
                    except Exception as exc:  # pragma: no cover - defensive fallback
                        failures.append(
                            {
                                "spectrum_id": spectrum.spectrum_id,
                                "model_name": model_name,
                                "error": str(exc),
                            }
                        )
        else:
            reason = (
                "pl_disabled_in_fitter"
                if modality == "pl" and not self.enable_pl
                else f"unsupported_modality:{modality}"
            )
            raw_candidates.append(
                self._fallback_candidate(
                    model_name="fallback_signal_tracking",
                    x_full=x_full,
                    y_corr=y_corr,
                    fit_status="attention",
                    attention_reasons=[reason],
                    extra_metrics=prefit_eval.metrics,
                )
            )

        if not raw_candidates:
            raw_candidates.append(
                self._fallback_candidate(
                    model_name="fallback_signal_tracking",
                    x_full=x_full,
                    y_corr=y_corr,
                    fit_status="invalid",
                    invalid_reasons=["fit_all_models_failed"],
                    attention_reasons=list(prefit_eval.attention_reasons),
                    extra_metrics=prefit_eval.metrics,
                )
            )

        candidates: list[FitCandidate] = []
        for candidate in raw_candidates:
            self._recompute_metrics_on_window(
                candidate,
                x_full=x_full,
                y_true=y_corr,
                x_min=cfg.compare_x_min,
                x_max=cfg.compare_x_max,
            )
            if modality == "raman":
                try:
                    candidate = self._maybe_auto_refine_candidate(
                        candidate=candidate,
                        x_full=x_full,
                        y_corr=y_corr,
                        cfg=cfg,
                    )
                except Exception as exc:
                    failures.append(
                        {
                            "spectrum_id": spectrum.spectrum_id,
                            "model_name": f"{candidate.model_name}(auto_refine)",
                            "error": str(exc),
                        }
                    )
            fit_invalid_reasons = self._candidate_math_invalid_reasons(candidate)
            candidates.append(
                self._apply_candidate_status(
                    candidate=candidate,
                    prefit_eval=prefit_eval,
                    fit_invalid_reasons=fit_invalid_reasons,
                )
            )

        prefit_info = {
            "status": prefit_eval.status,
            "invalid_reasons": list(prefit_eval.invalid_reasons),
            "attention_reasons": list(prefit_eval.attention_reasons),
            "metrics": dict(prefit_eval.metrics),
        }
        return _SpectrumFitResult(
            spectrum_id=spectrum.spectrum_id,
            modality=modality,
            candidates=candidates,
            prefit_info=prefit_info,
            failures=failures,
        )

    def run(
        self,
        spectra: Sequence[PreprocessedSpectrum],
        baselines: Mapping[str, BaselineResult],
        context: PipelineContext,
    ) -> Mapping[str, FitEnsembleResult]:
        ensemble: dict[str, FitEnsembleResult] = {}
        metadata_index = context.state.setdefault("spectrum_metadata", {})
        failures: list[dict[str, str]] = []
        fit_cache: dict[str, list[dict[str, Any]]] = {}
        prefit_index: dict[str, dict[str, Any]] = {}
        fit_status_counts: dict[str, int] = {"valid": 0, "attention": 0, "invalid": 0}
        modality_counts: dict[str, int] = {}

        def _include_candidate_fitted_y_for(modality_name: str) -> bool:
            section = context.config.get(modality_name, {}) if isinstance(context.config, dict) else {}
            if not isinstance(section, dict):
                return False
            report_export = section.get("report_export", {})
            if not isinstance(report_export, dict):
                return False
            return bool(report_export.get("include_candidate_fitted_y", False))

        cfg_by_modality: dict[str, RamanFitConfig] = {}
        modality_by_spectrum: dict[str, str] = {}
        progress_enabled = bool(context.state.get("progress_enabled", False))
        progress_every = max(int(_finite(context.state.get("progress_every", 5), 5.0)), 1)
        fit_workers = max(int(_finite(context.state.get("fit_workers", 1), 1.0)), 1)
        total = len(spectra)
        t0 = time.perf_counter()
        if progress_enabled and total > 0:
            print(f"[fit] start: {total} spectra", flush=True)

        for spectrum in spectra:
            metadata_index[spectrum.spectrum_id] = dict(spectrum.metadata)
            modality = self._resolve_modality(spectrum.metadata)
            modality_by_spectrum[spectrum.spectrum_id] = modality
            modality_counts[modality] = modality_counts.get(modality, 0) + 1

            cfg = cfg_by_modality.get(modality)
            if cfg is None:
                cfg = self._resolve_fit_config(
                    context,
                    modality="raman" if modality == "raman" else modality,
                )
                cfg_by_modality[modality] = cfg
        spectrum_by_id = {s.spectrum_id: s for s in spectra}
        results_by_id: dict[str, _SpectrumFitResult] = {}
        parallel_failed = False
        if fit_workers > 1 and total > 1:
            # Avoid CPU oversubscription: one process per spectrum task, one BLAS/OpenMP thread per process.
            for env_key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
                os.environ.setdefault(env_key, "1")

            max_workers = min(fit_workers, total)
            try:
                with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
                    futures: dict[concurrent.futures.Future[_SpectrumFitResult], str] = {}
                    for spectrum in spectra:
                        modality = modality_by_spectrum[spectrum.spectrum_id]
                        cfg = cfg_by_modality[modality]
                        baseline_y = baselines[spectrum.spectrum_id].selected.baseline_y
                        future = executor.submit(
                            _fit_single_spectrum_worker,
                            spectrum=spectrum,
                            baseline_y=list(baseline_y),
                            cfg=cfg,
                            enable_pl=self.enable_pl,
                        )
                        futures[future] = spectrum.spectrum_id

                    completed = 0
                    for future in concurrent.futures.as_completed(futures):
                        spectrum_id = futures[future]
                        try:
                            fit_result = future.result()
                        except concurrent.futures.BrokenExecutor:
                            # Pool itself died (e.g. frozen exe children failed to start): every
                            # pending future fails the same way, so hand the remaining spectra
                            # to the sequential path instead of marking them invalid.
                            raise
                        except Exception as exc:  # pragma: no cover - defensive fallback
                            modality = modality_by_spectrum.get(spectrum_id, "raman")
                            cfg = cfg_by_modality[modality]
                            spectrum = spectrum_by_id.get(spectrum_id)
                            if spectrum is None:
                                completed += 1
                                continue
                            x_full = np.asarray(spectrum.x, dtype=float)
                            y_full = np.asarray(spectrum.y, dtype=float)
                            baseline = np.asarray(baselines[spectrum.spectrum_id].selected.baseline_y, dtype=float)
                            y_corr = y_full - baseline
                            prefit_eval = (
                                self._evaluate_prefit_gate(x_full=x_full, y_corr=y_corr, cfg=cfg)
                                if modality == "raman" and x_full.size >= cfg.prefit.min_points
                                else self._default_prefit_evaluation()
                            )
                            fallback = self._fallback_candidate(
                                model_name="fit_worker_exception",
                                x_full=x_full,
                                y_corr=y_corr,
                                fit_status="invalid",
                                invalid_reasons=["fit_worker_exception"],
                                attention_reasons=list(prefit_eval.attention_reasons),
                                extra_metrics=prefit_eval.metrics,
                            )
                            fit_result = _SpectrumFitResult(
                                spectrum_id=spectrum_id,
                                modality=modality,
                                candidates=[
                                    self._apply_candidate_status(
                                        candidate=fallback,
                                        prefit_eval=prefit_eval,
                                        fit_invalid_reasons=["fit_worker_exception"],
                                    )
                                ],
                                prefit_info={
                                    "status": prefit_eval.status,
                                    "invalid_reasons": list(prefit_eval.invalid_reasons),
                                    "attention_reasons": list(prefit_eval.attention_reasons),
                                    "metrics": dict(prefit_eval.metrics),
                                },
                                failures=[
                                    {
                                        "spectrum_id": spectrum_id,
                                        "model_name": "__worker__",
                                        "error": str(exc),
                                    }
                                ],
                            )

                        results_by_id[spectrum_id] = fit_result
                        failures.extend(fit_result.failures)
                        prefit_index[spectrum_id] = dict(fit_result.prefit_info)
                        status = self._best_available_status(fit_result.candidates)
                        fit_status_counts[status] = fit_status_counts.get(status, 0) + 1

                        completed += 1
                        if progress_enabled and (completed % progress_every == 0 or completed == total):
                            elapsed = time.perf_counter() - t0
                            print(
                                "[fit] "
                                f"{completed}/{total} | valid={fit_status_counts.get('valid', 0)} "
                                f"attention={fit_status_counts.get('attention', 0)} "
                                f"invalid={fit_status_counts.get('invalid', 0)} "
                                f"| elapsed={elapsed:.1f}s",
                                flush=True,
                            )
            except Exception as exc:  # pragma: no cover - environment-dependent fallback
                parallel_failed = True
                failures.append(
                    {
                        "spectrum_id": "__all__",
                        "model_name": "process_pool_init",
                        "error": str(exc),
                    }
                )
                if progress_enabled:
                    print(f"[fit] multiprocessing disabled; fallback to sequential ({exc})", flush=True)

        if fit_workers <= 1 or total <= 1 or parallel_failed:
            completed = len(results_by_id)
            for spectrum in spectra:
                if spectrum.spectrum_id in results_by_id:
                    continue
                modality = modality_by_spectrum[spectrum.spectrum_id]
                cfg = cfg_by_modality[modality]
                fit_result = self._fit_spectrum(
                    spectrum=spectrum,
                    baseline_y=baselines[spectrum.spectrum_id].selected.baseline_y,
                    cfg=cfg,
                )
                results_by_id[spectrum.spectrum_id] = fit_result
                failures.extend(fit_result.failures)
                prefit_index[spectrum.spectrum_id] = dict(fit_result.prefit_info)
                status = self._best_available_status(fit_result.candidates)
                fit_status_counts[status] = fit_status_counts.get(status, 0) + 1

                completed += 1
                if progress_enabled and (completed % progress_every == 0 or completed == total):
                    elapsed = time.perf_counter() - t0
                    print(
                        "[fit] "
                        f"{completed}/{total} | valid={fit_status_counts.get('valid', 0)} "
                        f"attention={fit_status_counts.get('attention', 0)} "
                        f"invalid={fit_status_counts.get('invalid', 0)} "
                        f"| elapsed={elapsed:.1f}s",
                        flush=True,
                    )

        for spectrum in spectra:
            fit_result = results_by_id.get(spectrum.spectrum_id)
            if fit_result is None:
                continue
            modality = fit_result.modality
            candidates = fit_result.candidates
            ensemble[spectrum.spectrum_id] = FitEnsembleResult(modality=modality, candidates=candidates)
            fit_cache[spectrum.spectrum_id] = [
                self._serialize_candidate(
                    c,
                    include_fitted_y=_include_candidate_fitted_y_for(modality),
                )
                for c in candidates
            ]

        context.state["fit_count"] = len(ensemble)
        context.state["fit_failures"] = failures
        context.state["fit_ensemble_cache"] = fit_cache
        context.state["prefit_diagnostics"] = prefit_index
        context.state["fit_stage_status_counts"] = fit_status_counts
        context.state["input_modality_counts"] = modality_counts
        if len(modality_counts) == 1:
            context.state["run_modality"] = next(iter(modality_counts.keys()))
        elif len(modality_counts) > 1:
            context.state["run_modality"] = "mixed"
        else:
            context.state["run_modality"] = "raman"
        return ensemble


def _fit_single_spectrum_worker(
    *,
    spectrum: PreprocessedSpectrum,
    baseline_y: Sequence[float],
    cfg: RamanFitConfig,
    enable_pl: bool,
) -> _SpectrumFitResult:
    fitter = LmfitRamanModelEnsembleFitting(enable_pl=enable_pl)
    return fitter._fit_spectrum(
        spectrum=spectrum,
        baseline_y=baseline_y,
        cfg=cfg,
    )
