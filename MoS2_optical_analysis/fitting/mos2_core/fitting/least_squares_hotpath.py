"""Guardrail least-squares fit path for Raman n-peak candidates.

This module intentionally does not replace the production lmfit path yet.  It
implements the same first-pass Raman n-peak candidate shape behind an explicit
comparison runner so parity and speed can be measured before a default switch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
from scipy.optimize import least_squares

from ..core.types import FitCandidate
from .raman_lmfit import (
    RamanFitConfig,
    _bg_slope_bounds,
    _build_n_peak_spec,
    _estimate_linear_baseline_edges,
    _finite,
    _height_guess_to_lmfit_area,
    _sigma_bounds_for_peak,
)


_EPS = 1.0e-12


@dataclass(slots=True)
class _VarSpec:
    name: str
    initial: float
    lower: float
    upper: float


def _gaussian_normalized_curve(x: np.ndarray, *, center: float, sigma_l: float) -> np.ndarray:
    sigma_g = max(float(sigma_l), 1.0e-6) / np.sqrt(2.0 * np.log(2.0))
    z = (x - float(center)) / sigma_g
    return np.exp(-0.5 * z * z) / max(sigma_g * np.sqrt(2.0 * np.pi), _EPS)


def _lorentz_normalized_curve(x: np.ndarray, *, center: float, sigma_l: float) -> np.ndarray:
    sigma = max(float(sigma_l), 1.0e-6)
    return (1.0 / np.pi) * (sigma / (((x - float(center)) ** 2) + (sigma * sigma)))


def _pvoigt_component(
    x: np.ndarray,
    *,
    area: float,
    center: float,
    sigma: float,
    fraction: float,
) -> np.ndarray:
    frac = float(np.clip(fraction, 0.0, 1.0))
    return float(max(area, 0.0)) * (
        (1.0 - frac) * _gaussian_normalized_curve(x, center=center, sigma_l=sigma)
        + frac * _lorentz_normalized_curve(x, center=center, sigma_l=sigma)
    )


def _height_from_area_sigma(area: float, sigma: float, fraction: float) -> float:
    sigma_val = max(float(sigma), 1.0e-6)
    frac = float(np.clip(fraction, 0.0, 1.0))
    sigma_g = sigma_val / np.sqrt(2.0 * np.log(2.0))
    gaussian_height = 1.0 / max(sigma_g * np.sqrt(2.0 * np.pi), _EPS)
    lorentz_height = 1.0 / max(np.pi * sigma_val, _EPS)
    return float(max(area, 0.0)) * ((1.0 - frac) * gaussian_height + frac * lorentz_height)


def _fit_quality(y_true: np.ndarray, y_pred: np.ndarray, n_params: int, nfev: int) -> dict[str, float]:
    resid = y_true - y_pred
    n = int(y_true.size)
    rss = float(np.sum(resid**2))
    mse = max(rss / max(n, 1), 1.0e-12)
    rmse = float(np.sqrt(mse))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    r2 = float(1.0 - rss / ss_tot) if ss_tot > 0 else 0.0
    k = max(int(n_params), 1)
    return {
        "aic": float(n * np.log(mse) + 2.0 * k),
        "bic": float(n * np.log(mse) + k * np.log(max(n, 2))),
        "rmse": rmse,
        "r2": r2,
        "aic_fit": float(n * np.log(mse) + 2.0 * k),
        "bic_fit": float(n * np.log(mse) + k * np.log(max(n, 2))),
        "rmse_fit": rmse,
        "r2_fit": r2,
        "nfev": float(nfev),
        "n_params": float(k),
    }


def _add_var(specs: list[_VarSpec], name: str, initial: float, lower: float, upper: float) -> None:
    lo = float(lower)
    hi = float(upper)
    if not np.isfinite(lo):
        lo = -1.0e12
    if not np.isfinite(hi):
        hi = 1.0e12
    if hi <= lo:
        span = max(abs(float(initial)) * 1.0e-6, 1.0e-8)
        lo = float(initial) - span
        hi = float(initial) + span
    value = float(np.clip(float(initial), lo + 1.0e-12, hi - 1.0e-12))
    specs.append(_VarSpec(name=name, initial=value, lower=lo, upper=hi))


def fit_raman_n_peak_least_squares(
    *,
    model_name: str,
    x_full: np.ndarray,
    y_corr: np.ndarray,
    cfg: RamanFitConfig,
    anchor_centers: Mapping[str, float] | None = None,
    max_nfev: int | None = 2000,
) -> FitCandidate:
    """Fit one Raman n-peak candidate using scipy least_squares."""

    spec = _build_n_peak_spec(model_name, cfg)
    mask = (x_full >= spec.x_min) & (x_full <= spec.x_max)
    x_fit = np.asarray(x_full[mask], dtype=float)
    y_fit = np.asarray(y_corr[mask], dtype=float)
    if x_fit.size < cfg.min_roi_points:
        raise ValueError(f"Insufficient ROI points for model {model_name}")

    baseline_slope, baseline_intercept = _estimate_linear_baseline_edges(
        x_fit, y_fit, spec.left_base, spec.right_base
    )
    h_guess = max(float(np.max(y_fit) - np.min(y_fit)), 1.0)

    var_specs: list[_VarSpec] = []
    prefix_for_label: dict[str, str] = {}
    center_exprs: dict[str, tuple[str, str] | None] = {}

    if spec.lock_baseline:
        a_eps = max(1.0e-8, abs(baseline_slope) * cfg.locked_baseline_rel_tol)
        b_eps = max(1.0e-8, abs(baseline_intercept) * cfg.locked_baseline_rel_tol)
        _add_var(var_specs, "bg_slope", baseline_slope, baseline_slope - a_eps, baseline_slope + a_eps)
        _add_var(
            var_specs,
            "bg_intercept",
            baseline_intercept,
            baseline_intercept - b_eps,
            baseline_intercept + b_eps,
        )
    else:
        slope_bounds = _bg_slope_bounds(baseline_slope, cfg.bg_slope_min_half_width, cfg.bg_slope_multiplier)
        _add_var(var_specs, "bg_slope", baseline_slope, slope_bounds["min"], slope_bounds["max"])
        _add_var(var_specs, "bg_intercept", baseline_intercept, -1.0e12, 1.0e12)

    anchor_mode = (
        cfg.two_stage_anchor_enabled
        and model_name != "peak_2_model"
        and anchor_centers is not None
    )

    for idx, label in enumerate(spec.peak_labels):
        key = label.lower()
        prefix = f"p{idx}_"
        prefix_for_label[label] = prefix
        center_guess = float(spec.center_guesses[idx])

        if label == "E2g":
            center_min, center_max = cfg.e2g_bounds
        elif label == "A1g":
            center_min, center_max = cfg.a1g_bounds
        else:
            center_min = center_guess - spec.center_tolerance
            center_max = center_guess + spec.center_tolerance

        if (
            cfg.two_stage_anchor_enabled
            and model_name != "peak_2_model"
            and anchor_centers is not None
            and label in {"E2g", "A1g"}
        ):
            anchor_value = _finite(anchor_centers.get(key), default=float("nan"))
            if np.isfinite(anchor_value):
                center_guess = float(anchor_value)
                center_min = max(float(center_min), center_guess - cfg.two_stage_anchor_window)
                center_max = min(float(center_max), center_guess + cfg.two_stage_anchor_window)
                if center_max <= center_min:
                    center_min = center_guess - cfg.anchor_fallback_half_window
                    center_max = center_guess + cfg.anchor_fallback_half_window

        center_var = f"{key}_center"
        center_exprs[label] = None
        if cfg.enforce_peak_order and anchor_mode:
            if label in {"E2g", "A1g"}:
                _add_var(var_specs, center_var, center_guess, center_min, center_max)
            elif label == "LO" and "E2g" in prefix_for_label:
                delta_name = "d_lo_from_e2g"
                b = cfg.offset_bounds["lo_from_e2g"]
                delta_guess = max(abs(float(cfg.lo_offset_from_e2g)), b["min"])
                _add_var(var_specs, delta_name, delta_guess, b["min"], b["max"])
                center_exprs[label] = ("minus", delta_name)
            elif label == "ZO" and "A1g" in prefix_for_label:
                delta_name = "d_zo_from_a1g"
                b = cfg.offset_bounds["zo_from_a1g"]
                delta_guess = max(abs(float(cfg.zo_offset_from_a1g)), b["min"])
                _add_var(var_specs, delta_name, delta_guess, b["min"], max(b["max_floor"], delta_guess + b["max_margin"]))
                center_exprs[label] = ("plus_a1g", delta_name)
            elif label == "LA" and "A1g" in prefix_for_label:
                delta_name = "d_la_from_a1g"
                b = cfg.offset_bounds["la_from_a1g"]
                delta_guess = max(abs(float(cfg.la_offset_from_a1g)), b["min"])
                _add_var(var_specs, delta_name, delta_guess, b["min"], max(b["max_floor"], delta_guess + b["max_margin"]))
                center_exprs[label] = ("plus_a1g", delta_name)
            elif idx == 0:
                _add_var(var_specs, center_var, center_guess, center_min, center_max)
            else:
                prev_label = spec.peak_labels[idx - 1]
                prev_guess = spec.center_guesses[idx - 1]
                delta_name = f"d_{prev_label.lower()}_{key}"
                chain = cfg.offset_bounds["chain"]
                _add_var(var_specs, delta_name, max(center_guess - prev_guess, chain["guess_floor"]), chain["min"], chain["max"])
                center_exprs[label] = ("plus_prev", delta_name)
        elif idx == 0 or not cfg.enforce_peak_order or (anchor_mode and label in {"E2g", "A1g"}):
            _add_var(var_specs, center_var, center_guess, center_min, center_max)
        else:
            prev_label = spec.peak_labels[idx - 1]
            prev_guess = spec.center_guesses[idx - 1]
            delta_name = f"d_{prev_label.lower()}_{key}"
            chain = cfg.offset_bounds["chain"]
            _add_var(var_specs, delta_name, max(center_guess - prev_guess, chain["guess_floor"]), chain["min"], chain["max"])
            center_exprs[label] = ("plus_prev", delta_name)

        sigma_min, sigma_max = _sigma_bounds_for_peak(cfg, label)
        sigma_guess = float(np.clip(float(spec.width_guesses[idx]), sigma_min, sigma_max))
        fraction_guess = float(cfg.fraction_init)
        area_guess = _height_guess_to_lmfit_area(
            height_guess=float(spec.height_scales[idx] * h_guess),
            sigma_guess=sigma_guess,
            fraction_guess=fraction_guess,
        )
        _add_var(var_specs, f"{key}_sigma", sigma_guess, sigma_min, sigma_max)
        _add_var(var_specs, f"{key}_area", max(area_guess, 1.0e-6), 0.0, 1.0e12)
        _add_var(var_specs, f"{key}_fraction", fraction_guess, 0.0, 1.0)

    names = [item.name for item in var_specs]
    x0 = np.asarray([item.initial for item in var_specs], dtype=float)
    lower = np.asarray([item.lower for item in var_specs], dtype=float)
    upper = np.asarray([item.upper for item in var_specs], dtype=float)

    def _values(vector: np.ndarray) -> dict[str, float]:
        return {name: float(vector[i]) for i, name in enumerate(names)}

    def _centers(values: Mapping[str, float]) -> dict[str, float]:
        centers: dict[str, float] = {}
        for idx, label in enumerate(spec.peak_labels):
            key = label.lower()
            expr = center_exprs.get(label)
            if expr is None:
                centers[label] = float(values[f"{key}_center"])
                continue
            mode, delta_name = expr
            if mode == "minus":
                centers[label] = float(centers["E2g"] - values[delta_name])
            elif mode == "plus_a1g":
                centers[label] = float(centers["A1g"] + values[delta_name])
            else:
                centers[label] = float(centers[spec.peak_labels[idx - 1]] + values[delta_name])
        return centers

    def _eval(vector: np.ndarray, x_axis: np.ndarray) -> np.ndarray:
        values = _values(vector)
        centers = _centers(values)
        y_pred = (values["bg_slope"] * x_axis) + values["bg_intercept"]
        for label in spec.peak_labels:
            key = label.lower()
            y_pred = y_pred + _pvoigt_component(
                x_axis,
                area=values[f"{key}_area"],
                center=centers[label],
                sigma=values[f"{key}_sigma"],
                fraction=values[f"{key}_fraction"],
            )
        return np.asarray(y_pred, dtype=float)

    result = least_squares(
        lambda vector: _eval(vector, x_fit) - y_fit,
        x0,
        bounds=(lower, upper),
        max_nfev=max_nfev,
    )
    values = _values(result.x)
    centers = _centers(values)
    y_fit_pred = _eval(result.x, x_fit)
    y_full_pred = _eval(result.x, np.asarray(x_full, dtype=float))

    params: dict[str, Any] = {
        "bg_slope": values["bg_slope"],
        "bg_intercept": values["bg_intercept"],
        "line_profile": "pvoigt",
    }
    peak_heights: list[tuple[str, float, float]] = []
    for label in spec.peak_labels:
        key = label.lower()
        center = centers[label]
        sigma = values[f"{key}_sigma"]
        area = values[f"{key}_area"]
        fraction = values[f"{key}_fraction"]
        height = _height_from_area_sigma(area=area, sigma=sigma, fraction=fraction)
        params[f"{key}_position"] = float(center)
        params[f"{key}_fwhm"] = float(2.0 * sigma)
        params[f"{key}_height"] = float(height)
        params[f"{key}_area"] = float(area)
        params[f"{key}_sigma"] = float(sigma)
        params[f"{key}_fraction"] = float(fraction)
        peak_heights.append((label, float(center), float(height)))

    if "e2g_position" in params and "a1g_position" in params:
        params["delta_e2g_a1g"] = float(params["a1g_position"] - params["e2g_position"])
    if "e2g_position" in params:
        params["peak_position"] = float(params["e2g_position"])
    elif peak_heights:
        params["peak_position"] = float(max(peak_heights, key=lambda item: item[2])[1])
    if "e2g_height" in params and "a1g_height" in params:
        params["peak_amplitude"] = float(max(params["e2g_height"], params["a1g_height"]))
    elif peak_heights:
        params["peak_amplitude"] = float(max(item[2] for item in peak_heights))

    metrics = _fit_quality(
        y_true=y_fit,
        y_pred=y_fit_pred,
        n_params=len(var_specs),
        nfev=int(result.nfev),
    )
    metrics["least_squares_cost"] = float(result.cost)
    metrics["least_squares_status"] = float(result.status)
    metrics["least_squares_success"] = 1.0 if bool(result.success) else 0.0

    return FitCandidate(
        model_name=model_name,
        params=params,
        fitted_y=[float(v) for v in y_full_pred],
        metrics=metrics,
    )
