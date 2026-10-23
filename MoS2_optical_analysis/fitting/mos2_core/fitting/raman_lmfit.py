"""LMFIT-based Raman model ensemble fitting implementations."""

from __future__ import annotations

import concurrent.futures
import os
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
from lmfit.model import ModelResult
from lmfit.models import GaussianModel, LinearModel, LorentzianModel, PseudoVoigtModel

from ..core.interfaces import ModelEnsembleFittingStage
from ..core.types import BaselineResult, FitCandidate, FitEnsembleResult, PipelineContext, PreprocessedSpectrum


@dataclass(slots=True)
class NPeakWindowSpec:
    """ROI and baseline-edge windows for one N-peak model."""

    x_min: float
    x_max: float
    left_base: tuple[float, float]
    right_base: tuple[float, float]


@dataclass(slots=True)
class RamanFitConfig:
    """Runtime Raman fit configuration resolved from YAML."""

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
    sigma_bounds: tuple[float, float]
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


@dataclass(slots=True)
class PreFitConfig:
    """Configuration for pre-fit peak-evidence gating."""

    enabled: bool
    peak_window_half_width: float
    e2g_snr_hard_min: float
    e2g_snr_soft_min: float
    a1g_snr_hard_min: float
    a1g_snr_soft_min: float
    noise_left: tuple[float, float]
    noise_right: tuple[float, float]


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


def _resolve_models(raw_models: Any, default_models: Sequence[str]) -> list[str]:
    if not isinstance(raw_models, list):
        return list(default_models)

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

    return names or list(default_models)


def _resolve_height_scales(raw: Any) -> dict[str, list[float]]:
    if not isinstance(raw, dict):
        return {}
    resolved: dict[str, list[float]] = {}
    for model_name, values in raw.items():
        if not isinstance(model_name, str) or not isinstance(values, list):
            continue
        parsed: list[float] = []
        for value in values:
            number = _finite(value, default=float("nan"))
            if np.isfinite(number) and number >= 0.0:
                parsed.append(float(number))
        if parsed:
            resolved[model_name] = parsed
    return resolved


def _resolve_center_tolerances(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    resolved: dict[str, float] = {}
    for model_name, value in raw.items():
        if not isinstance(model_name, str):
            continue
        tol = _finite(value, default=float("nan"))
        if np.isfinite(tol) and tol > 0.0:
            resolved[model_name] = float(tol)
    return resolved


def _resolve_sigma_bounds_by_peak(raw: Any) -> dict[str, tuple[float, float]]:
    if not isinstance(raw, dict):
        return {}
    resolved: dict[str, tuple[float, float]] = {}
    for peak_name, spec in raw.items():
        if not isinstance(peak_name, str):
            continue

        sigma_min = float("nan")
        sigma_max = float("nan")
        if isinstance(spec, dict):
            sigma_min = _finite(spec.get("min"), default=float("nan"))
            sigma_max = _finite(spec.get("max"), default=float("nan"))
        elif isinstance(spec, (list, tuple)) and len(spec) >= 2:
            sigma_min = _finite(spec[0], default=float("nan"))
            sigma_max = _finite(spec[1], default=float("nan"))

        if np.isfinite(sigma_min) and np.isfinite(sigma_max) and sigma_max > sigma_min:
            resolved[peak_name.lower()] = (float(sigma_min), float(sigma_max))
    return resolved


def _pl_component_key(name: str) -> str:
    normalized = str(name).strip().lower().replace("-", "_minus")
    normalized = normalized.replace("+", "_plus")
    normalized = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in normalized)
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_") or "component"


def _fwhm_to_sigma(fwhm: float, profile: str) -> float:
    fwhm_value = max(float(fwhm), 1.0e-9)
    return fwhm_value / 2.354820045 if profile == "gaussian" else fwhm_value / 2.0


def _resolve_pl_components(raw: Any) -> dict[str, PLComponentSpec]:
    defaults: dict[str, dict[str, Any]] = {
        "pl": {
            "label": "PL",
            "profile": "pvoigt",
            "center_init": 1.85,
            "center_min": 1.50,
            "center_max": 2.15,
            "fwhm_init": 0.12,
            "fwhm_min": 0.004,
            "fwhm_max": 0.40,
            "height_scale": 1.00,
        },
        "i1": {
            "label": "I1",
            "profile": "pvoigt",
            "center_init": 1.51,
            "center_min": 1.43,
            "center_max": 1.58,
            "fwhm_init": 0.13,
            "fwhm_min": 0.03,
            "fwhm_max": 0.24,
            "height_scale": 0.15,
        },
        "i2": {
            "label": "I2",
            "profile": "pvoigt",
            "center_init": 1.61,
            "center_min": 1.54,
            "center_max": 1.70,
            "fwhm_init": 0.20,
            "fwhm_min": 0.04,
            "fwhm_max": 0.32,
            "height_scale": 0.20,
        },
        "a_minus": {
            "label": "A-",
            "profile": "pvoigt",
            "center_init": 1.855,
            "center_min": 1.78,
            "center_max": 1.90,
            "fwhm_init": 0.085,
            "fwhm_min": 0.02,
            "fwhm_max": 0.18,
            "height_scale": 1.00,
        },
        "a0": {
            "label": "A0",
            "profile": "pvoigt",
            "center_init": 1.882,
            "center_min": 1.84,
            "center_max": 1.93,
            "fwhm_init": 0.045,
            "fwhm_min": 0.01,
            "fwhm_max": 0.12,
            "height_scale": 0.30,
        },
        "b": {
            "label": "B",
            "profile": "pvoigt",
            "center_init": 2.022,
            "center_min": 1.94,
            "center_max": 2.10,
            "fwhm_init": 0.125,
            "fwhm_min": 0.03,
            "fwhm_max": 0.24,
            "height_scale": 0.25,
        },
    }

    entries = {**defaults, **raw} if isinstance(raw, dict) else defaults
    resolved: dict[str, PLComponentSpec] = {}
    for raw_name, raw_spec in entries.items():
        if not isinstance(raw_spec, dict):
            continue
        key = _pl_component_key(str(raw_spec.get("key", raw_name)))
        default = defaults.get(key, {})
        label = str(raw_spec.get("label", default.get("label", key))).strip() or key
        profile = str(raw_spec.get("profile", default.get("profile", "pvoigt"))).strip().lower()
        if profile not in {"pvoigt", "gaussian"}:
            profile = "pvoigt"

        center_init = _finite(raw_spec.get("center_init", default.get("center_init")), 1.85)
        center_min = _finite(raw_spec.get("center_min", default.get("center_min")), center_init - 0.05)
        center_max = _finite(raw_spec.get("center_max", default.get("center_max")), center_init + 0.05)
        if center_max <= center_min:
            center_min, center_max = center_init - 0.05, center_init + 0.05

        sigma_init_raw = raw_spec.get("sigma_init")
        sigma_min_raw = raw_spec.get("sigma_min")
        sigma_max_raw = raw_spec.get("sigma_max")
        if sigma_init_raw is None:
            sigma_init = _fwhm_to_sigma(_finite(raw_spec.get("fwhm_init", default.get("fwhm_init")), 0.1), profile)
        else:
            sigma_init = _finite(sigma_init_raw, 0.05)
        if sigma_min_raw is None:
            sigma_min = _fwhm_to_sigma(_finite(raw_spec.get("fwhm_min", default.get("fwhm_min")), 0.01), profile)
        else:
            sigma_min = _finite(sigma_min_raw, 0.005)
        if sigma_max_raw is None:
            sigma_max = _fwhm_to_sigma(_finite(raw_spec.get("fwhm_max", default.get("fwhm_max")), 0.25), profile)
        else:
            sigma_max = _finite(sigma_max_raw, 0.125)
        if sigma_max <= sigma_min:
            sigma_min, sigma_max = 0.002, 0.20
        sigma_init = float(np.clip(sigma_init, sigma_min, sigma_max))

        resolved[key] = PLComponentSpec(
            key=key,
            label=label,
            profile=profile,
            center_init=float(np.clip(center_init, center_min, center_max)),
            center_min=float(center_min),
            center_max=float(center_max),
            sigma_init=float(sigma_init),
            sigma_min=float(sigma_min),
            sigma_max=float(sigma_max),
            height_scale=max(_finite(raw_spec.get("height_scale", default.get("height_scale")), 1.0), 0.0),
            amplitude_min=max(_finite(raw_spec.get("amplitude_min", default.get("amplitude_min", 0.0)), 0.0), 0.0),
            fraction_init=float(np.clip(_finite(raw_spec.get("fraction_init", default.get("fraction_init", 0.5)), 0.5), 0.0, 1.0)),
            vary_center=bool(raw_spec.get("vary_center", default.get("vary_center", True))),
            vary_sigma=bool(raw_spec.get("vary_sigma", default.get("vary_sigma", True))),
            vary_amplitude=bool(raw_spec.get("vary_amplitude", default.get("vary_amplitude", True))),
            vary_fraction=bool(raw_spec.get("vary_fraction", default.get("vary_fraction", True))),
        )

    if not resolved:
        return _resolve_pl_components(defaults)
    return resolved


def _resolve_pl_model_components(raw: Any) -> dict[str, list[str]]:
    defaults = {
        "pl_single_pvoigt": ["pl"],
        "pl_single_gaussian": ["pl"],
        "pl_a_doublet_pvoigt": ["a_minus", "a0"],
        "pl_5_component_pvoigt": ["i1", "i2", "a_minus", "a0", "b"],
    }
    if not isinstance(raw, dict):
        return defaults
    resolved = dict(defaults)
    for model_name, components in raw.items():
        if not isinstance(model_name, str) or not isinstance(components, list):
            continue
        keys = [_pl_component_key(str(item)) for item in components if str(item).strip()]
        if keys:
            resolved[model_name] = keys
    return resolved


def _resolve_window_pair(raw: Any, default: tuple[float, float]) -> tuple[float, float]:
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        lo = _finite(raw[0], default=float("nan"))
        hi = _finite(raw[1], default=float("nan"))
        if np.isfinite(lo) and np.isfinite(hi):
            return (float(min(lo, hi)), float(max(lo, hi)))
    if isinstance(raw, dict):
        lo = _finite(raw.get("min"), default=float("nan"))
        hi = _finite(raw.get("max"), default=float("nan"))
        if np.isfinite(lo) and np.isfinite(hi):
            return (float(min(lo, hi)), float(max(lo, hi)))
    return default


def _resolve_prefit_config(raw: Any) -> PreFitConfig:
    if not isinstance(raw, dict):
        raw = {}
    noise = raw.get("noise_windows", {})
    if not isinstance(noise, dict):
        noise = {}

    return PreFitConfig(
        enabled=bool(raw.get("enabled", True)),
        peak_window_half_width=max(_finite(raw.get("peak_window_half_width", 2.5), 2.5), 0.5),
        e2g_snr_hard_min=max(_finite(raw.get("e2g_snr_hard_min", raw.get("snr_hard_min", 2.5)), 2.5), 0.1),
        e2g_snr_soft_min=max(_finite(raw.get("e2g_snr_soft_min", raw.get("snr_soft_min", 4.0)), 4.0), 0.1),
        a1g_snr_hard_min=max(_finite(raw.get("a1g_snr_hard_min", raw.get("snr_hard_min", 2.5)), 2.5), 0.1),
        a1g_snr_soft_min=max(_finite(raw.get("a1g_snr_soft_min", raw.get("snr_soft_min", 4.0)), 4.0), 0.1),
        noise_left=_resolve_window_pair(noise.get("left"), default=(350.0, 360.0)),
        noise_right=_resolve_window_pair(noise.get("right"), default=(430.0, 440.0)),
    )


def _default_baseline_windows_from_roi(x_min: float, x_max: float) -> tuple[tuple[float, float], tuple[float, float]]:
    span = max(float(x_max) - float(x_min), 1.0)
    edge = max(1.0, 0.1 * span)
    left = (float(x_min), float(x_min + edge))
    right = (float(x_max - edge), float(x_max))
    return left, right


def _resolve_model_windows(raw: Any, global_x_min: float, global_x_max: float) -> dict[str, NPeakWindowSpec]:
    if not isinstance(raw, dict):
        return {}

    resolved: dict[str, NPeakWindowSpec] = {}
    for model_name, spec in raw.items():
        if not isinstance(model_name, str) or not isinstance(spec, dict):
            continue

        x_min = _finite(spec.get("x_min"), default=float("nan"))
        x_max = _finite(spec.get("x_max"), default=float("nan"))
        if not (np.isfinite(x_min) and np.isfinite(x_max) and x_max > x_min):
            x_min = float(global_x_min)
            x_max = float(global_x_max)
        else:
            x_min = float(x_min)
            x_max = float(x_max)

        default_left, default_right = _default_baseline_windows_from_roi(x_min, x_max)
        left_base = _resolve_window_pair(spec.get("left_base"), default=default_left)
        right_base = _resolve_window_pair(spec.get("right_base"), default=default_right)
        resolved[model_name] = NPeakWindowSpec(
            x_min=x_min,
            x_max=x_max,
            left_base=left_base,
            right_base=right_base,
        )

    return resolved


def _height_scales_for_model(
    cfg: RamanFitConfig,
    model_name: str,
    defaults: list[float],
) -> list[float]:
    configured = cfg.height_scales.get(model_name)
    if configured is None or len(configured) != len(defaults):
        return list(defaults)
    return list(configured)


def _center_tolerance_for_model(cfg: RamanFitConfig, model_name: str, default: float) -> float:
    return float(cfg.center_tolerance_by_model.get(model_name, default))


def _sigma_bounds_for_peak(cfg: RamanFitConfig, peak_label: str) -> tuple[float, float]:
    specific = cfg.sigma_bounds_by_peak.get(str(peak_label).lower())
    if specific is not None:
        return specific
    return cfg.sigma_bounds


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


def _bg_slope_bounds(baseline_slope: float) -> dict[str, float]:
    """Slope search range centred on the edge estimate so steep backgrounds are not clamped."""
    half_width = max(2.0, 3.0 * abs(baseline_slope))
    return {"min": baseline_slope - half_width, "max": baseline_slope + half_width}


def _noise_std_from_windows(
    x: np.ndarray,
    y: np.ndarray,
    left_window: tuple[float, float],
    right_window: tuple[float, float],
) -> float:
    left_mask = (x >= left_window[0]) & (x <= left_window[1])
    right_mask = (x >= right_window[0]) & (x <= right_window[1])
    noise_mask = left_mask | right_mask
    noise = y[noise_mask]
    if noise.size < 8:
        low = float(np.percentile(y, 35))
        noise = y[y <= low]
    if noise.size < 5:
        noise = y
    sigma = float(np.std(noise))
    return max(sigma, 1.0e-6)


def _window_peak_height(
    x: np.ndarray,
    y: np.ndarray,
    center: float,
    half_width: float,
) -> tuple[float, float]:
    mask = (x >= (center - half_width)) & (x <= (center + half_width))
    if int(np.sum(mask)) < 3:
        return 0.0, float(center)
    yw = y[mask]
    xw = x[mask]
    peak_idx = int(np.argmax(yw))
    baseline_local = float(np.percentile(yw, 20))
    prominence = float(max(yw[peak_idx] - baseline_local, 0.0))
    return prominence, float(xw[peak_idx])


def _build_n_peak_spec(model_name: str, cfg: RamanFitConfig) -> NPeakSpec:
    lo_init = cfg.e2g_init + cfg.lo_offset_from_e2g
    zo_init = cfg.a1g_init + cfg.zo_offset_from_a1g
    la_init = cfg.a1g_init + cfg.la_offset_from_a1g
    window = cfg.model_windows.get(model_name)
    if window is None:
        default_left, default_right = _default_baseline_windows_from_roi(cfg.x_min, cfg.x_max)
        window = NPeakWindowSpec(
            x_min=float(cfg.x_min),
            x_max=float(cfg.x_max),
            left_base=default_left,
            right_base=default_right,
        )

    if model_name == "peak_2_model":
        height_scales = _height_scales_for_model(cfg, model_name, defaults=[0.50, 0.90])
        center_tolerance = _center_tolerance_for_model(cfg, model_name, default=5.0)
        return NPeakSpec(
            model_name=model_name,
            peak_labels=["E2g", "A1g"],
            center_guesses=[cfg.e2g_init, cfg.a1g_init],
            width_guesses=[3.0, 3.0],
            height_scales=height_scales,
            x_min=window.x_min,
            x_max=window.x_max,
            left_base=window.left_base,
            right_base=window.right_base,
            center_tolerance=center_tolerance,
            lock_baseline=False,
        )

    if model_name == "peak_3_model":
        height_scales = _height_scales_for_model(cfg, model_name, defaults=[0.12, 0.50, 0.90])
        center_tolerance = _center_tolerance_for_model(cfg, model_name, default=2.5)
        return NPeakSpec(
            model_name=model_name,
            peak_labels=["LO", "E2g", "A1g"],
            center_guesses=[lo_init, cfg.e2g_init, cfg.a1g_init],
            width_guesses=[7.0, 3.0, 3.0],
            height_scales=height_scales,
            x_min=window.x_min,
            x_max=window.x_max,
            left_base=window.left_base,
            right_base=window.right_base,
            center_tolerance=center_tolerance,
            lock_baseline=True,
        )

    if model_name == "peak_4_model":
        height_scales = _height_scales_for_model(cfg, model_name, defaults=[0.12, 0.50, 0.90, 0.20])
        center_tolerance = _center_tolerance_for_model(cfg, model_name, default=2.5)
        return NPeakSpec(
            model_name=model_name,
            peak_labels=["LO", "E2g", "A1g", "ZO"],
            center_guesses=[lo_init, cfg.e2g_init, cfg.a1g_init, zo_init],
            width_guesses=[7.0, 3.0, 3.0, 4.0],
            height_scales=height_scales,
            x_min=window.x_min,
            x_max=window.x_max,
            left_base=window.left_base,
            right_base=window.right_base,
            center_tolerance=center_tolerance,
            lock_baseline=True,
        )

    if model_name == "peak_5_model":
        height_scales = _height_scales_for_model(cfg, model_name, defaults=[0.12, 0.50, 0.90, 0.20, 0.20])
        center_tolerance = _center_tolerance_for_model(cfg, model_name, default=2.5)
        return NPeakSpec(
            model_name=model_name,
            peak_labels=["LO", "E2g", "A1g", "ZO", "LA"],
            center_guesses=[lo_init, cfg.e2g_init, cfg.a1g_init, zo_init, la_init],
            width_guesses=[7.0, 3.0, 3.0, 4.0, 8.0],
            height_scales=height_scales,
            x_min=window.x_min,
            x_max=window.x_max,
            left_base=window.left_base,
            right_base=window.right_base,
            center_tolerance=center_tolerance,
            lock_baseline=True,
        )

    raise ValueError(f"Unsupported n-peak model: {model_name}")


class LmfitRamanModelEnsembleFitting(ModelEnsembleFittingStage):
    """
    Raman/PL ensemble fitter using multiple candidate models.

    Supported model names in `raman.models`:
    - peak_2_model
    - peak_3_model
    - peak_4_model
    - peak_5_model
    - mos2_double_pvoigt
    - mos2_double_lorentz
    - mos2_double_gaussian

    Supported model names in `pl.models`:
    - pl_single_gaussian
    - pl_single_pvoigt
    - pl_a_doublet_pvoigt
    - pl_5_component_pvoigt
    """

    def __init__(
        self,
        default_models: Sequence[str] | None = None,
        pl_models: Sequence[str] | None = None,
        enable_pl: bool = True,
    ) -> None:
        self.default_models = list(
            default_models or ["peak_2_model", "peak_3_model", "peak_4_model", "peak_5_model"]
        )
        self.pl_models = list(
            pl_models or ["pl_single_pvoigt", "pl_a_doublet_pvoigt", "pl_5_component_pvoigt"]
        )
        self.enable_pl = bool(enable_pl)

    def _resolve_fit_config(self, context: PipelineContext, modality: str) -> RamanFitConfig:
        section = context.config.get(modality, {}) if isinstance(context.config, dict) else {}
        if not isinstance(section, dict):
            section = {}

        fit_cfg = section.get("fit", {})
        if not isinstance(fit_cfg, dict):
            fit_cfg = {}

        is_pl = modality == "pl"
        default_models = self.pl_models if is_pl else self.default_models
        models = _resolve_models(section.get("models", default_models), default_models)
        x_min_default = 1.38 if is_pl else 340.0
        x_max_default = 2.33 if is_pl else 430.0
        x_min = _finite(fit_cfg.get("x_min", x_min_default), x_min_default)
        x_max = _finite(fit_cfg.get("x_max", x_max_default), x_max_default)
        center_init_default = 1.85 if is_pl else 384.0
        center_min_default = x_min + 0.05 if is_pl else 370.0
        center_max_default = x_max - 0.05 if is_pl else 392.0
        sigma_min_default = 0.002 if is_pl else 0.5
        sigma_max_default = 0.20 if is_pl else 20.0
        prefit_cfg = (
            {
                "enabled": False,
                "peak_window_half_width": 2.5,
                "e2g_snr_hard_min": 0.0,
                "e2g_snr_soft_min": 0.0,
                "a1g_snr_hard_min": 0.0,
                "a1g_snr_soft_min": 0.0,
                "noise_windows": {
                    "left": [x_min, x_min + max((x_max - x_min) * 0.1, 1.0)],
                    "right": [x_max - max((x_max - x_min) * 0.1, 1.0), x_max],
                },
            }
            if is_pl
            else fit_cfg.get("prefit", {})
        )
        two_stage_anchor_cfg = fit_cfg.get("two_stage_anchor", {})
        if not isinstance(two_stage_anchor_cfg, dict):
            two_stage_anchor_cfg = {}
        auto_refine_cfg = fit_cfg.get("auto_refine", {})
        if not isinstance(auto_refine_cfg, dict):
            auto_refine_cfg = {}
        two_stage_anchor_enabled = bool(
            two_stage_anchor_cfg.get("enabled", not is_pl)
        )
        two_stage_anchor_window = max(
            _finite(
                two_stage_anchor_cfg.get("window", 2.0),
                2.0,
            ),
            0.0,
        )
        auto_refine_enabled = bool(auto_refine_cfg.get("enabled", False))
        auto_refine_min_rmse_improvement = max(
            _finite(auto_refine_cfg.get("min_rmse_improvement", 0.01), 0.01),
            0.0,
        )
        a_minus_a0_split_cfg = fit_cfg.get("a_minus_a0_split", {})
        if not isinstance(a_minus_a0_split_cfg, dict):
            a_minus_a0_split_cfg = {}
        split_enabled = bool(a_minus_a0_split_cfg.get("enabled", is_pl))
        split_min = _finite(a_minus_a0_split_cfg.get("min", 0.015), 0.015)
        split_max = _finite(a_minus_a0_split_cfg.get("max", 0.055), 0.055)
        split_init = _finite(a_minus_a0_split_cfg.get("init", 0.030), 0.030)
        pl_a_minus_a0_split = (split_enabled, split_min, split_max, split_init)

        fwhm_ratio_cfg = fit_cfg.get("trion_exciton_fwhm_ratio", {})
        if not isinstance(fwhm_ratio_cfg, dict):
            fwhm_ratio_cfg = {}
        ratio_enabled = bool(fwhm_ratio_cfg.get("enabled", is_pl))
        ratio_min = _finite(fwhm_ratio_cfg.get("min", 1.05), 1.05)
        ratio_max = _finite(fwhm_ratio_cfg.get("max", 2.50), 2.50)
        ratio_init = _finite(fwhm_ratio_cfg.get("init", 1.35), 1.35)
        pl_trion_exciton_fwhm_ratio = (ratio_enabled, ratio_min, ratio_max, ratio_init)

        pl_share_exciton_fraction = bool(fit_cfg.get("share_exciton_fraction", is_pl))

        return RamanFitConfig(
            models=models,
            x_min=x_min,
            x_max=x_max,
            e2g_init=_finite(
                fit_cfg.get("pl_center_init", fit_cfg.get("e2g_init", center_init_default)),
                center_init_default,
            ),
            a1g_init=_finite(
                fit_cfg.get("a1g_init", fit_cfg.get("pl_center_init", center_init_default)),
                center_init_default,
            ),
            lo_offset_from_e2g=_finite(fit_cfg.get("lo_offset_from_e2g", -5.0), -5.0),
            zo_offset_from_a1g=_finite(fit_cfg.get("zo_offset_from_a1g", 5.0), 5.0),
            la_offset_from_a1g=_finite(fit_cfg.get("la_offset_from_a1g", 50.0), 50.0),
            height_scales=_resolve_height_scales(
                fit_cfg.get("height_scales", fit_cfg.get("amplitude_scales", {}))
            ),
            center_tolerance_by_model=_resolve_center_tolerances(
                fit_cfg.get("center_tolerance_by_model", {})
            ),
            e2g_bounds=(
                _finite(fit_cfg.get("pl_center_min", fit_cfg.get("e2g_min", center_min_default)), center_min_default),
                _finite(fit_cfg.get("pl_center_max", fit_cfg.get("e2g_max", center_max_default)), center_max_default),
            ),
            a1g_bounds=(
                _finite(fit_cfg.get("a1g_min", 395.0), 395.0),
                _finite(fit_cfg.get("a1g_max", 415.0), 415.0),
            ),
            sigma_bounds=(
                _finite(fit_cfg.get("pl_sigma_min", fit_cfg.get("sigma_min", sigma_min_default)), sigma_min_default),
                _finite(fit_cfg.get("pl_sigma_max", fit_cfg.get("sigma_max", sigma_max_default)), sigma_max_default),
            ),
            sigma_bounds_by_peak=_resolve_sigma_bounds_by_peak(
                fit_cfg.get("sigma_bounds_by_peak", {})
            ),
            compare_x_min=_finite(fit_cfg.get("compare_x_min", x_min), x_min),
            compare_x_max=_finite(fit_cfg.get("compare_x_max", x_max), x_max),
            enforce_peak_order=bool(fit_cfg.get("enforce_peak_order", not is_pl)),
            two_stage_anchor_enabled=two_stage_anchor_enabled,
            two_stage_anchor_window=two_stage_anchor_window,
            auto_refine_enabled=auto_refine_enabled,
            auto_refine_min_rmse_improvement=auto_refine_min_rmse_improvement,
            prefit=_resolve_prefit_config(prefit_cfg),
            model_windows=_resolve_model_windows(
                fit_cfg.get("model_windows", {}),
                global_x_min=x_min,
                global_x_max=x_max,
            ),
            pl_components=_resolve_pl_components(fit_cfg.get("components", fit_cfg.get("pl_components", {}))),
            pl_model_components=_resolve_pl_model_components(fit_cfg.get("model_components", {})),
            pl_a_minus_a0_split=pl_a_minus_a0_split,
            pl_trion_exciton_fwhm_ratio=pl_trion_exciton_fwhm_ratio,
            pl_share_exciton_fraction=pl_share_exciton_fraction,
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

        noise_std = _noise_std_from_windows(
            x_full,
            y_corr,
            left_window=prefit.noise_left,
            right_window=prefit.noise_right,
        )
        e2g_height, e2g_peak_x = _window_peak_height(
            x_full,
            y_corr,
            center=cfg.e2g_init,
            half_width=prefit.peak_window_half_width,
        )
        a1g_height, a1g_peak_x = _window_peak_height(
            x_full,
            y_corr,
            center=cfg.a1g_init,
            half_width=prefit.peak_window_half_width,
        )
        e2g_snr = e2g_height / max(noise_std, 1.0e-6)
        a1g_snr = a1g_height / max(noise_std, 1.0e-6)

        invalid_reasons: list[str] = []
        attention_reasons: list[str] = []
        if e2g_snr < prefit.e2g_snr_hard_min:
            invalid_reasons.append("prefit_e2g_snr_below_hard")
        if a1g_snr < prefit.a1g_snr_hard_min:
            invalid_reasons.append("prefit_a1g_snr_below_hard")
        if not invalid_reasons:
            if e2g_snr < prefit.e2g_snr_soft_min:
                attention_reasons.append("prefit_e2g_snr_below_soft")
            if a1g_snr < prefit.a1g_snr_soft_min:
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
                "aic": rmse + 100.0,
                "bic": rmse + 101.0,
                "rmse": rmse,
                "r2": 0.0,
                "is_valid_candidate": 0.0 if fit_status == "invalid" else 1.0,
                **(dict(extra_metrics or {})),
            },
        )

    @staticmethod
    def _build_two_peak_model(model_name: str):
        if model_name == "mos2_double_pvoigt":
            e2g = PseudoVoigtModel(prefix="e2g_")
            a1g = PseudoVoigtModel(prefix="a1g_")
        elif model_name == "mos2_double_lorentz":
            e2g = LorentzianModel(prefix="e2g_")
            a1g = LorentzianModel(prefix="a1g_")
        elif model_name == "mos2_double_gaussian":
            e2g = GaussianModel(prefix="e2g_")
            a1g = GaussianModel(prefix="a1g_")
        else:
            raise ValueError(f"Unsupported two-peak model: {model_name}")
        bg = LinearModel(prefix="bg_")
        return e2g + a1g + bg

    def _fit_pl_model(
        self,
        model_name: str,
        x_full: np.ndarray,
        y_corr: np.ndarray,
        cfg: RamanFitConfig,
    ) -> FitCandidate:
        component_keys = cfg.pl_model_components.get(model_name)
        if component_keys:
            return self._fit_pl_component_model(
                model_name=model_name,
                component_keys=component_keys,
                x_full=x_full,
                y_corr=y_corr,
                cfg=cfg,
            )

        mask = self._mask_roi(x_full, cfg.x_min, cfg.x_max)
        x_fit = x_full[mask]
        y_fit = y_corr[mask]
        if x_fit.size < 20:
            raise ValueError(f"Insufficient ROI points for PL model {model_name}")

        if model_name == "pl_single_pvoigt":
            peak_model = PseudoVoigtModel(prefix="pl_")
            fraction_guess = 0.5
        elif model_name == "pl_single_gaussian":
            peak_model = GaussianModel(prefix="pl_")
            fraction_guess = 0.0
        else:
            raise ValueError(f"Unsupported PL model: {model_name}")

        model = LinearModel(prefix="bg_") + peak_model
        params = model.make_params()
        left_base, right_base = _default_baseline_windows_from_roi(cfg.x_min, cfg.x_max)
        baseline_slope, baseline_intercept = _estimate_linear_baseline_edges(
            x_fit, y_fit, left_base, right_base
        )
        params["bg_slope"].set(value=baseline_slope, min=-2.0, max=2.0)
        params["bg_intercept"].set(value=baseline_intercept)

        peak_idx = int(np.argmax(y_fit))
        center_seed = float(x_fit[peak_idx])
        center_min = float(min(cfg.e2g_bounds))
        center_max = float(max(cfg.e2g_bounds))
        if center_max <= center_min:
            center_min = float(np.min(x_fit))
            center_max = float(np.max(x_fit))
        center_guess = float(np.clip(cfg.e2g_init, center_min, center_max))
        if not np.isfinite(center_guess):
            center_guess = float(np.clip(center_seed, center_min, center_max))

        sigma_min, sigma_max = _sigma_bounds_for_peak(cfg, "pl")
        if sigma_max <= sigma_min:
            sigma_min, sigma_max = cfg.sigma_bounds
        sigma_guess = float(np.clip(0.5 * (sigma_min + sigma_max), sigma_min, sigma_max))
        baseline_guess = float(np.percentile(y_fit, 20))
        height_guess = max(float(np.max(y_fit) - baseline_guess), 1.0e-6)
        area_guess_lmfit = _height_guess_to_lmfit_area(
            height_guess=height_guess,
            sigma_guess=sigma_guess,
            fraction_guess=fraction_guess,
        )

        params["pl_center"].set(value=center_guess, min=center_min, max=center_max)
        params["pl_sigma"].set(value=sigma_guess, min=sigma_min, max=sigma_max)
        params["pl_amplitude"].set(value=max(area_guess_lmfit, 1.0e-6), min=0.0)
        if "pl_fraction" in params:
            params["pl_fraction"].set(value=fraction_guess, min=0.0, max=1.0)

        fit_result = model.fit(y_fit, params, x=x_fit, nan_policy="omit")
        y_pred_full = model.eval(fit_result.params, x=x_full)
        return self._candidate_from_result(
            model_name=model_name,
            fit_result=fit_result,
            x_fit=x_fit,
            y_fit=y_fit,
            x_full=x_full,
            y_pred_full=np.asarray(y_pred_full, dtype=float),
            peak_labels=["PL"],
            prefix_for_label={"PL": "pl_"},
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
        if x_fit.size < 20:
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
        left_base, right_base = _default_baseline_windows_from_roi(cfg.x_min, cfg.x_max)
        baseline_slope, baseline_intercept = _estimate_linear_baseline_edges(
            x_fit, y_fit, left_base, right_base
        )
        params["bg_slope"].set(value=baseline_slope)
        params["bg_intercept"].set(value=baseline_intercept)

        y_low = float(np.percentile(y_fit, 20))
        dynamic_height = max(float(np.max(y_fit) - y_low), 1.0e-6)
        for spec in selected_components:
            prefix = f"{spec.key}_"
            local_half_width = max(
                float(spec.center_init - spec.center_min),
                float(spec.center_max - spec.center_init),
                0.02,
            )
            local_height, local_center = _window_peak_height(
                x_fit,
                y_fit,
                center=spec.center_init,
                half_width=local_half_width,
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

            amplitude_floor = max(spec.amplitude_min, area_guess_lmfit * 0.01, 1.0e-3)
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
    ) -> FitCandidate:
        y_best = fit_result.best_fit
        rmse, r2 = self._fit_quality(y_fit, y_best)

        if model_name in {
            "peak_2_model",
            "peak_3_model",
            "peak_4_model",
            "peak_5_model",
            "mos2_double_pvoigt",
            "pl_single_pvoigt",
            "pl_a_doublet_pvoigt",
            "pl_5_component_pvoigt",
        }:
            line_profile = "pvoigt"
        elif model_name == "mos2_double_lorentz":
            line_profile = "lorentz"
        elif model_name in {"mos2_double_gaussian", "pl_single_gaussian"}:
            line_profile = "gaussian"
        else:
            line_profile = "unknown"

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
            if model_name.startswith("pl_"):
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

        if model_name.startswith("pl_"):
            residual = np.asarray(y_fit, dtype=float) - np.asarray(y_best, dtype=float)
            if residual.size:
                resid_med = float(np.median(residual))
                resid_mad = float(np.median(np.abs(residual - resid_med)))
                resid_sigma = max(1.4826 * resid_mad, 1.0e-9)
                positive_resid = float(np.max(residual))
                y_span = float(np.percentile(y_fit, 95) - np.percentile(y_fit, 5))
                spike_threshold = max(12.0 * resid_sigma, 0.60 * max(y_span, 1.0e-9))
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

    def _fit_two_peak_legacy(
        self,
        model_name: str,
        x_full: np.ndarray,
        y_corr: np.ndarray,
        cfg: RamanFitConfig,
    ) -> FitCandidate:
        mask = self._mask_roi(x_full, cfg.x_min, cfg.x_max)
        x_fit = x_full[mask]
        y_fit = y_corr[mask]
        if x_fit.size < 20:
            raise ValueError("Insufficient ROI points for two-peak model")

        model = self._build_two_peak_model(model_name)
        params = model.make_params()
        baseline_guess = float(np.percentile(y_fit, 20))
        height_guess = max(float(np.max(y_fit) - baseline_guess), 1.0)

        params["bg_intercept"].set(value=baseline_guess)
        params["bg_slope"].set(value=0.0, min=-2.0, max=2.0)
        params["e2g_center"].set(value=cfg.e2g_init, min=cfg.e2g_bounds[0], max=cfg.e2g_bounds[1])
        params["a1g_center"].set(value=cfg.a1g_init, min=cfg.a1g_bounds[0], max=cfg.a1g_bounds[1])
        if model_name == "mos2_double_pvoigt":
            fraction_guess = 0.5
            e2g_area_guess_lmfit = _height_guess_to_lmfit_area(height_guess, sigma_guess=4.0, fraction_guess=fraction_guess)
            a1g_area_guess_lmfit = _height_guess_to_lmfit_area(height_guess, sigma_guess=4.0, fraction_guess=fraction_guess)
        elif model_name == "mos2_double_lorentz":
            e2g_area_guess_lmfit = height_guess * (np.pi * 4.0)
            a1g_area_guess_lmfit = height_guess * (np.pi * 4.0)
        else:
            e2g_area_guess_lmfit = height_guess * (4.0 * np.sqrt(2.0 * np.pi))
            a1g_area_guess_lmfit = height_guess * (4.0 * np.sqrt(2.0 * np.pi))

        params["e2g_amplitude"].set(value=max(e2g_area_guess_lmfit, 1.0e-6), min=0.0)
        params["a1g_amplitude"].set(value=max(a1g_area_guess_lmfit, 1.0e-6), min=0.0)

        if "e2g_sigma" in params:
            e2g_sigma_min, e2g_sigma_max = _sigma_bounds_for_peak(cfg, "e2g")
            e2g_sigma_guess = float(np.clip(4.0, e2g_sigma_min, e2g_sigma_max))
            params["e2g_sigma"].set(value=e2g_sigma_guess, min=e2g_sigma_min, max=e2g_sigma_max)
        if "a1g_sigma" in params:
            a1g_sigma_min, a1g_sigma_max = _sigma_bounds_for_peak(cfg, "a1g")
            a1g_sigma_guess = float(np.clip(4.0, a1g_sigma_min, a1g_sigma_max))
            params["a1g_sigma"].set(value=a1g_sigma_guess, min=a1g_sigma_min, max=a1g_sigma_max)
        if "e2g_fraction" in params:
            params["e2g_fraction"].set(value=0.5, min=0.0, max=1.0)
        if "a1g_fraction" in params:
            params["a1g_fraction"].set(value=0.5, min=0.0, max=1.0)

        fit_result = model.fit(y_fit, params, x=x_fit, nan_policy="omit")
        y_pred_full = model.eval(fit_result.params, x=x_full)
        return self._candidate_from_result(
            model_name=model_name,
            fit_result=fit_result,
            x_fit=x_fit,
            y_fit=y_fit,
            x_full=x_full,
            y_pred_full=np.asarray(y_pred_full, dtype=float),
            peak_labels=["E2g", "A1g"],
            prefix_for_label={"E2g": "e2g_", "A1g": "a1g_"},
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
        if x_fit.size < 20:
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
            a_eps = max(1.0e-8, abs(baseline_slope) * 0.01)
            b_eps = max(1.0e-8, abs(baseline_intercept) * 0.01)
            params["bg_slope"].set(value=baseline_slope, min=baseline_slope - a_eps, max=baseline_slope + a_eps)
            params["bg_intercept"].set(
                value=baseline_intercept,
                min=baseline_intercept - b_eps,
                max=baseline_intercept + b_eps,
            )
        else:
            params["bg_slope"].set(value=baseline_slope, **_bg_slope_bounds(baseline_slope))
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
            fraction_guess = 0.0
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
                        center_min, center_max = center_guess - 0.5, center_guess + 0.5

            anchor_locked = anchor_mode and label in {"E2g", "A1g"}
            center_name = f"{prefix}center"

            # In anchor mode, avoid prev->next chain and use anchor-centric offsets:
            # LO <- E2g, ZO/LA <- A1g. This keeps dependency local to anchor peaks.
            if cfg.enforce_peak_order and anchor_mode:
                if anchor_locked:
                    params[center_name].set(value=center_guess, min=center_min, max=center_max)
                elif label == "LO" and "E2g" in prefix_for_label:
                    delta_name = "d_lo_from_e2g"
                    delta_guess = max(abs(float(cfg.lo_offset_from_e2g)), 0.5)
                    params.add(delta_name, value=delta_guess, min=0.5, max=10.0)
                    params[center_name].set(expr=f"{prefix_for_label['E2g']}center - {delta_name}")
                elif label == "ZO" and "A1g" in prefix_for_label:
                    delta_name = "d_zo_from_a1g"
                    delta_guess = max(abs(float(cfg.zo_offset_from_a1g)), 0.5)
                    delta_max = max(20.0, delta_guess + 10.0)
                    params.add(delta_name, value=delta_guess, min=0.5, max=delta_max)
                    params[center_name].set(expr=f"{prefix_for_label['A1g']}center + {delta_name}")
                elif label == "LA" and "A1g" in prefix_for_label:
                    delta_name = "d_la_from_a1g"
                    delta_guess = max(abs(float(cfg.la_offset_from_a1g)), 0.5)
                    delta_max = max(70.0, delta_guess + 20.0)
                    params.add(delta_name, value=delta_guess, min=0.5, max=delta_max)
                    params[center_name].set(expr=f"{prefix_for_label['A1g']}center + {delta_name}")
                elif idx == 0:
                    params[center_name].set(value=center_guess, min=center_min, max=center_max)
                else:
                    prev_label = spec.peak_labels[idx - 1]
                    prev_prefix = prefix_for_label[prev_label]
                    prev_guess = spec.center_guesses[idx - 1]
                    delta_guess = max(center_guess - prev_guess, 1.0)
                    delta_name = f"d_{prev_label.lower()}_{label.lower()}"
                    params.add(delta_name, value=delta_guess, min=0.5, max=60.0)
                    params[center_name].set(expr=f"{prev_prefix}center + {delta_name}")
            elif idx == 0 or not cfg.enforce_peak_order or anchor_locked:
                params[center_name].set(value=center_guess, min=center_min, max=center_max)
            else:
                prev_label = spec.peak_labels[idx - 1]
                prev_prefix = prefix_for_label[prev_label]
                prev_guess = spec.center_guesses[idx - 1]
                delta_guess = max(center_guess - prev_guess, 1.0)
                delta_name = f"d_{prev_label.lower()}_{label.lower()}"
                params.add(delta_name, value=delta_guess, min=0.5, max=60.0)
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
            normalized_model = {
                "signal_tracking_stub": "pl_single_gaussian",
                "flat_stub": "pl_single_pvoigt",
                "fallback_signal_tracking": "pl_single_gaussian",
                "fallback_flat": "pl_single_pvoigt",
                "fallback": "pl_single_gaussian",
            }.get(model_name, model_name)
            if normalized_model in cfg.pl_model_components or normalized_model in {"pl_single_gaussian", "pl_single_pvoigt"}:
                return self._fit_pl_model(normalized_model, x_full, y_corr, cfg)
            raise ValueError(f"Unsupported PL model: {model_name}")

        if model_name in {"mos2_double_pvoigt", "mos2_double_lorentz", "mos2_double_gaussian"}:
            return self._fit_two_peak_legacy(model_name, x_full, y_corr, cfg)
        if model_name in {"peak_2_model", "peak_3_model", "peak_4_model", "peak_5_model"}:
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
        if x_fit.size < 20:
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
            a_eps = max(1.0e-8, abs(baseline_slope) * 0.01)
            b_eps = max(1.0e-8, abs(baseline_intercept) * 0.01)
            params["bg_slope"].set(value=baseline_slope, min=baseline_slope - a_eps, max=baseline_slope + a_eps)
            params["bg_intercept"].set(
                value=baseline_intercept,
                min=baseline_intercept - b_eps,
                max=baseline_intercept + b_eps,
            )
        else:
            params["bg_slope"].set(value=baseline_slope, **_bg_slope_bounds(baseline_slope))
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
            fraction_guess = float(np.clip(_finite(initial_params.get(f"{peak_key}_fraction"), 0.0), 0.0, 1.0))

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
        if modality == "raman" and x_full.size >= 8:
            prefit_eval = self._evaluate_prefit_gate(x_full=x_full, y_corr=y_corr, cfg=cfg)
        else:
            prefit_eval = self._default_prefit_evaluation()

        raw_candidates: list[FitCandidate] = []
        if modality == "raman":
            if x_full.size < 20:
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
            if x_full.size < 20:
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
                            default_models=self.default_models,
                            pl_models=self.pl_models,
                            enable_pl=self.enable_pl,
                        )
                        futures[future] = spectrum.spectrum_id

                    completed = 0
                    for future in concurrent.futures.as_completed(futures):
                        spectrum_id = futures[future]
                        try:
                            fit_result = future.result()
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
                                if modality == "raman" and x_full.size >= 8
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
    default_models: Sequence[str],
    pl_models: Sequence[str],
    enable_pl: bool,
) -> _SpectrumFitResult:
    fitter = LmfitRamanModelEnsembleFitting(
        default_models=default_models,
        pl_models=pl_models,
        enable_pl=enable_pl,
    )
    return fitter._fit_spectrum(
        spectrum=spectrum,
        baseline_y=baseline_y,
        cfg=cfg,
    )
