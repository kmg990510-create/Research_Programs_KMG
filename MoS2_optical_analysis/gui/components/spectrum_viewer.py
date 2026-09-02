"""Spectrum-level plotting and helpers for raw/fitted overlays."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import plotly.graph_objects as go
import streamlit as st
from lmfit.models import GaussianModel, LorentzianModel, PseudoVoigtModel

from .plot_theme import apply_plotly_theme

apply_plotly_theme()

_DEFAULT_PEAK_STYLE: dict[str, dict[str, Any]] = {
    "pl": {"label": "PL", "color": "#E60000", "fill": True},
    "i1": {"label": "I1", "color": "#7A5195", "fill": True},
    "i2": {"label": "I2", "color": "#BC5090", "fill": True},
    "a_minus": {"label": "A-", "color": "#EF5675", "fill": True},
    "a0": {"label": "A0", "color": "#FFA600", "fill": True},
    "b": {"label": "B", "color": "#2F4B7C", "fill": True},
    "lo": {"label": "LO", "color": "#CC00CC", "fill": True},
    "e2g": {"label": "E2g", "color": "#0066FF", "fill": False},
    "a1g": {"label": "A1g", "color": "#00A651", "fill": False},
    "zo": {"label": "ZO", "color": "#00B7C7", "fill": True},
    "la": {"label": "LA", "color": "#F3C300", "fill": True},
}

_DEFAULT_OVERLAY_STYLE: dict[str, Any] = {
    "raw_marker_color": "#666666",
    "raw_marker_size": 6,
    "raw_marker_opacity": 0.60,
    "fit_line_color": "#FF1E1E",
    "fit_line_width": 4.0,
    "baseline_color": "#111111",
    "baseline_width": 2.0,
    "baseline_dash": "dash",
    "component_line_width": 2.8,
    "component_line_dash": "dot",
    "component_fill_alpha": 0.18,
    "component_colors": {k: v["color"] for k, v in _DEFAULT_PEAK_STYLE.items()},
}

_DEFAULT_FIT_CURVE_CFG: dict[str, Any] = {
    "smooth_factor": 5,
    "max_points": 4000,
}
NM_TO_EV = 1239.8419843320026


def resolve_source_file(source_value: Any, project_root: Path) -> Path | None:
    if not isinstance(source_value, str) or not source_value.strip():
        return None
    candidate = Path(source_value)
    if candidate.is_absolute() and candidate.exists():
        return candidate

    rel_candidate = project_root / candidate
    if rel_candidate.exists():
        return rel_candidate
    return None


@st.cache_data(show_spinner=False)
def load_raw_xy(source_path_str: str) -> tuple[list[float], list[float]]:
    from fitting.mos2_core.io import parse_raman_txt

    spectrum = parse_raman_txt(Path(source_path_str))
    return list(spectrum.x), list(spectrum.y)


def _gaussian_from_height_fwhm(
    x: np.ndarray,
    center: float,
    height: float,
    fwhm: float,
) -> np.ndarray:
    if fwhm <= 0:
        return np.zeros_like(x)
    return height * np.exp(-4.0 * np.log(2.0) * ((x - center) / fwhm) ** 2)


def _component_from_model_params(
    x: np.ndarray,
    row: dict[str, Any],
    key: str,
) -> tuple[np.ndarray, bool]:
    """Return component-only y from stored lmfit params; second flag is approximation usage."""
    center = _to_float(row.get(f"{key}_position"))
    area = _to_float(row.get(f"{key}_area"))
    sigma = _to_float(row.get(f"{key}_sigma"))
    profile = str(row.get(f"{key}_line_profile", row.get("line_profile", "pvoigt"))).strip().lower()

    if np.isfinite(center) and np.isfinite(area) and np.isfinite(sigma) and sigma > 0:
        prefix = f"{key}_"
        if profile == "pvoigt":
            model = PseudoVoigtModel(prefix=prefix)
            frac = _to_float(row.get(f"{key}_fraction"), default=0.0)
            if not np.isfinite(frac):
                frac = 0.0
            frac = float(np.clip(frac, 0.0, 1.0))
            params = model.make_params()
            params[f"{prefix}amplitude"].set(value=float(max(area, 0.0)))
            params[f"{prefix}center"].set(value=float(center))
            params[f"{prefix}sigma"].set(value=float(sigma))
            params[f"{prefix}fraction"].set(value=frac)
            return np.asarray(model.eval(params, x=x), dtype=float), False

        if profile == "lorentz":
            model = LorentzianModel(prefix=prefix)
            params = model.make_params()
            params[f"{prefix}amplitude"].set(value=float(max(area, 0.0)))
            params[f"{prefix}center"].set(value=float(center))
            params[f"{prefix}sigma"].set(value=float(sigma))
            return np.asarray(model.eval(params, x=x), dtype=float), False

        if profile == "gaussian":
            model = GaussianModel(prefix=prefix)
            params = model.make_params()
            params[f"{prefix}amplitude"].set(value=float(max(area, 0.0)))
            params[f"{prefix}center"].set(value=float(center))
            params[f"{prefix}sigma"].set(value=float(sigma))
            return np.asarray(model.eval(params, x=x), dtype=float), False

    # Fallback for old reports without area/sigma/fraction
    height = _to_float(row.get(f"{key}_height"))
    fwhm = _to_float(row.get(f"{key}_fwhm"))
    if np.isfinite(center) and np.isfinite(height) and np.isfinite(fwhm):
        return _gaussian_from_height_fwhm(x, center, height, fwhm), True
    return np.zeros_like(x), True


def _to_float(value: Any, default: float = np.nan) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    code = hex_color.strip().lstrip("#")
    if len(code) != 6:
        return f"rgba(128,128,128,{alpha})"
    r = int(code[0:2], 16)
    g = int(code[2:4], 16)
    b = int(code[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _style_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def _style_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(fallback)


def _resolve_overlay_style(style_cfg: dict[str, Any] | None) -> dict[str, Any]:
    style: dict[str, Any] = dict(_DEFAULT_OVERLAY_STYLE)
    style["component_colors"] = dict(_DEFAULT_OVERLAY_STYLE["component_colors"])

    if isinstance(style_cfg, dict):
        for key in [
            "raw_marker_color",
            "fit_line_color",
            "baseline_color",
            "baseline_dash",
            "component_line_dash",
        ]:
            value = style_cfg.get(key)
            if isinstance(value, str) and value.strip():
                style[key] = value.strip()

        style["raw_marker_size"] = _style_int(style_cfg.get("raw_marker_size"), style["raw_marker_size"])
        style["raw_marker_opacity"] = _style_float(style_cfg.get("raw_marker_opacity"), style["raw_marker_opacity"])
        style["fit_line_width"] = _style_float(style_cfg.get("fit_line_width"), style["fit_line_width"])
        style["baseline_width"] = _style_float(style_cfg.get("baseline_width"), style["baseline_width"])
        style["component_line_width"] = _style_float(style_cfg.get("component_line_width"), style["component_line_width"])
        style["component_fill_alpha"] = _style_float(style_cfg.get("component_fill_alpha"), style["component_fill_alpha"])

        component_colors = style_cfg.get("component_colors")
        if isinstance(component_colors, dict):
            for key, value in component_colors.items():
                if isinstance(key, str) and isinstance(value, str) and key.strip() and value.strip():
                    style["component_colors"][key.strip().lower()] = value.strip()

    style["raw_marker_opacity"] = float(np.clip(style["raw_marker_opacity"], 0.0, 1.0))
    style["component_fill_alpha"] = float(np.clip(style["component_fill_alpha"], 0.0, 1.0))
    style["raw_marker_size"] = max(1, int(style["raw_marker_size"]))
    style["fit_line_width"] = max(1.0e-3, float(style["fit_line_width"]))
    style["baseline_width"] = max(1.0e-3, float(style["baseline_width"]))
    style["component_line_width"] = max(1.0e-3, float(style["component_line_width"]))
    return style


def _resolve_fit_curve_cfg(fit_curve_cfg: dict[str, Any] | None) -> dict[str, Any]:
    cfg = dict(_DEFAULT_FIT_CURVE_CFG)
    if isinstance(fit_curve_cfg, dict):
        cfg["smooth_factor"] = _style_int(fit_curve_cfg.get("smooth_factor"), cfg["smooth_factor"])
        cfg["max_points"] = _style_int(fit_curve_cfg.get("max_points"), cfg["max_points"])
    cfg["smooth_factor"] = max(1, int(cfg["smooth_factor"]))
    cfg["max_points"] = max(32, int(cfg["max_points"]))
    return cfg


def _build_dense_x_axis(x_axis: np.ndarray, fit_curve_cfg: dict[str, Any]) -> np.ndarray:
    if x_axis.size <= 1:
        return np.asarray(x_axis, dtype=float)
    smooth_factor = max(1, int(fit_curve_cfg.get("smooth_factor", 1)))
    max_points = max(32, int(fit_curve_cfg.get("max_points", 4000)))
    target_points = max(x_axis.size, min(max_points, x_axis.size * smooth_factor))
    if target_points <= x_axis.size:
        return np.asarray(x_axis, dtype=float)
    return np.linspace(float(np.min(x_axis)), float(np.max(x_axis)), int(target_points))


def _interp_to_dense(x_src: np.ndarray, y_src: np.ndarray, x_dst: np.ndarray) -> np.ndarray:
    if x_src.size == 0 or y_src.size == 0:
        return np.zeros_like(x_dst, dtype=float)
    finite_mask = np.isfinite(x_src) & np.isfinite(y_src)
    if not np.any(finite_mask):
        return np.zeros_like(x_dst, dtype=float)
    x_valid = x_src[finite_mask]
    y_valid = y_src[finite_mask]
    order = np.argsort(x_valid)
    x_sorted = x_valid[order]
    y_sorted = y_valid[order]
    if x_sorted.size == 0:
        return np.zeros_like(x_dst, dtype=float)
    x_unique, unique_idx = np.unique(x_sorted, return_index=True)
    y_unique = y_sorted[unique_idx]
    if x_unique.size == 1:
        return np.full_like(x_dst, float(y_unique[0]), dtype=float)
    return np.interp(x_dst, x_unique, y_unique, left=float(y_unique[0]), right=float(y_unique[-1]))


def _auto_view_window(
    x: np.ndarray,
    e2g_pos: float,
    a1g_pos: float,
    padding: float = 18.0,
    pl_pos: float = np.nan,
) -> tuple[float, float]:
    if np.isfinite(pl_pos):
        x_span = float(np.max(x) - np.min(x))
        if x_span <= 10.0:
            pl_padding = max(0.08, min(0.25, x_span * 0.25))
        else:
            pl_padding = max(padding, 60.0)
        lo = pl_pos - pl_padding
        hi = pl_pos + pl_padding
        return max(lo, float(np.min(x))), min(hi, float(np.max(x)))
    if np.isfinite(e2g_pos) and np.isfinite(a1g_pos):
        lo = min(e2g_pos, a1g_pos) - padding
        hi = max(e2g_pos, a1g_pos) + padding
        return max(lo, float(np.min(x))), min(hi, float(np.max(x)))
    return float(np.min(x)), float(np.max(x))


def render_spectrum_overlay(
    spectrum_id: str,
    row: dict[str, Any],
    x_raw: list[float],
    y_raw: list[float],
    x_view_min: float | None = None,
    x_view_max: float | None = None,
    style_cfg: dict[str, Any] | None = None,
    fit_curve_cfg: dict[str, Any] | None = None,
) -> None:
    x = np.asarray(x_raw, dtype=float)
    y = np.asarray(y_raw, dtype=float)
    if x.size == 0 or y.size == 0:
        st.warning("Raw spectrum is empty.")
        return

    modality = str(row.get("modality", "")).strip().lower()
    is_pl_row = modality == "pl" or str(row.get("x_unit", "")).strip().lower() == "ev"
    if is_pl_row and x.size == y.size and np.nanmax(x) > 100.0:
        valid = np.isfinite(x) & np.isfinite(y) & (x > 0.0)
        x = NM_TO_EV / x[valid]
        y = y[valid]
        order = np.argsort(x)
        x = x[order]
        y = y[order]

    style = _resolve_overlay_style(style_cfg)
    fit_cfg = _resolve_fit_curve_cfg(fit_curve_cfg)

    fitted_values = row.get("fitted_y")
    has_fitted = isinstance(fitted_values, list) and len(fitted_values) == len(x_raw)
    y_fit_full = np.asarray(fitted_values, dtype=float) if has_fitted else None

    e2g_c = _to_float(row.get("e2g_position"))
    a1g_c = _to_float(row.get("a1g_position"))
    pl_c = _to_float(row.get("pl_position"))

    if x_view_min is None or x_view_max is None:
        x_view_min, x_view_max = _auto_view_window(x, e2g_c, a1g_c, pl_pos=pl_c)

    x_min = max(float(np.min(x)), float(min(x_view_min, x_view_max)))
    x_max = min(float(np.max(x)), float(max(x_view_min, x_view_max)))
    mask = (x >= x_min) & (x <= x_max)
    if not np.any(mask):
        st.warning("No points in selected x-range.")
        return

    x_plot = x[mask]
    y_plot = y[mask]
    y_fit_window = y_fit_full[mask] if y_fit_full is not None else None
    x_dense = _build_dense_x_axis(x_plot, fit_cfg)

    bg_slope = _to_float(row.get("bg_slope"), default=np.nan)
    bg_intercept = _to_float(row.get("bg_intercept"), default=np.nan)
    if np.isfinite(bg_slope) and np.isfinite(bg_intercept):
        baseline = bg_slope * x_plot + bg_intercept
        baseline_dense = bg_slope * x_dense + bg_intercept
    else:
        # fallback baseline when report row does not contain bg params
        y0 = float(y_plot[0])
        y1 = float(y_plot[-1])
        slope = (y1 - y0) / max(float(x_plot[-1] - x_plot[0]), 1e-9)
        intercept = y0 - slope * float(x_plot[0])
        baseline = slope * x_plot + intercept
        baseline_dense = slope * x_dense + intercept

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=x_plot,
            y=y_plot,
            mode="markers",
            name="Data",
            marker={
                "size": int(style["raw_marker_size"]),
                "color": str(style["raw_marker_color"]),
                "opacity": float(style["raw_marker_opacity"]),
            },
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x_dense,
            y=baseline_dense,
            mode="lines",
            name="Baseline",
            line={
                "color": str(style["baseline_color"]),
                "dash": str(style["baseline_dash"]),
                "width": float(style["baseline_width"]),
            },
        )
    )

    peak_style = {key: dict(values) for key, values in _DEFAULT_PEAK_STYLE.items()}
    component_colors = style.get("component_colors", {})
    if isinstance(component_colors, dict):
        for key, color in component_colors.items():
            if key in peak_style and isinstance(color, str) and color.strip():
                peak_style[key]["color"] = color.strip()

    used_component_approx = False
    component_sum_dense = np.zeros_like(x_dense, dtype=float)
    component_count = 0
    for key, peak_info in peak_style.items():
        center = _to_float(row.get(f"{key}_position"))
        if not np.isfinite(center):
            continue

        component_y_dense, used_approx = _component_from_model_params(x_dense, row, key)
        component_sum_dense = component_sum_dense + component_y_dense
        component_count += 1
        if bool(used_approx):
            used_component_approx = True
        curve_dense = component_y_dense + baseline_dense
        fig.add_trace(
            go.Scatter(
                x=x_dense,
                y=curve_dense,
                mode="lines",
                name=peak_info["label"],
                line={
                    "color": peak_info["color"],
                    "dash": str(style["component_line_dash"]),
                    "width": float(style["component_line_width"]),
                },
            )
        )
        if peak_info["fill"]:
            fig.add_trace(
                go.Scatter(
                    x=np.concatenate([x_dense, x_dense[::-1]]),
                    y=np.concatenate([curve_dense, baseline_dense[::-1]]),
                    fill="toself",
                    fillcolor=_hex_to_rgba(peak_info["color"], float(style["component_fill_alpha"])),
                    line={"color": "rgba(0,0,0,0)"},
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

    reconstructed_total_fit = False
    y_fit_dense: np.ndarray | None = None
    if y_fit_window is not None:
        y_fit_dense = _interp_to_dense(x_plot, y_fit_window, x_dense)
    elif component_count > 0:
        y_fit_dense = baseline_dense + component_sum_dense
        reconstructed_total_fit = True

    if y_fit_dense is not None:
        fig.add_trace(
            go.Scatter(
                x=x_dense,
                y=y_fit_dense,
                mode="lines",
                name="Total Fit (reconstructed)" if reconstructed_total_fit else "Total Fit",
                line={"color": str(style["fit_line_color"]), "width": float(style["fit_line_width"])},
            )
        )

    is_pl = modality == "pl" or np.isfinite(pl_c)
    if is_pl:
        pl_pos = row.get("pl_position")
        pl_text = f"{float(pl_pos):.4f} eV" if isinstance(pl_pos, (int, float)) and np.isfinite(float(pl_pos)) else str(pl_pos or "NA")
        title = f"{spectrum_id} | PL Peak: {pl_text}"
        xaxis_title = "Energy (eV)"
    else:
        delta_text = row.get("delta_e2g_a1g", "NA")
        title = f"{spectrum_id} | Delta(E2g-A1g): {delta_text}"
        xaxis_title = "Raman Shift (cm^-1)"

    fig.update_layout(
        template="plotly_white",
        title=title,
        xaxis_title=xaxis_title,
        yaxis_title="Intensity",
        hovermode="x unified",
        legend={
            "orientation": "v",
            "x": 1.02,
            "y": 1.0,
            "xanchor": "left",
            "yanchor": "top",
            "bgcolor": "rgba(255,255,255,0.85)",
            "bordercolor": "rgba(0,0,0,0.2)",
            "borderwidth": 1,
        },
        margin={"l": 60, "r": 220, "t": 60, "b": 60},
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(0,0,0,0.08)")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(0,0,0,0.08)")
    st.plotly_chart(fig, width="stretch")

    if used_component_approx:
        st.info("This row was plotted with component approximation (legacy report without area/sigma/fraction).")


def render_fit_summary(
    row: dict[str, Any],
    *,
    download_key: str | None = None,
) -> None:
    def _fmt(v: Any, digits: int = 3) -> str:
        try:
            return f"{float(v):.{digits}f}"
        except (TypeError, ValueError):
            return "NA"

    def _fwhm_warn(v: Any) -> str:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return "(!)"
        if str(row.get("modality", "")).strip().lower() == "pl":
            return "(!)" if (f <= 0.0 or f >= 0.5) else ""
        return "(!)" if (f < 3.0 or f >= 60.0) else ""

    modality = str(row.get("modality", "")).strip().lower()
    is_pl = modality == "pl" or "pl_position" in row

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Model", str(row.get("selected_model", "NA")))
    if is_pl:
        c2.metric("PL Peak (eV)", _fmt(row.get("pl_position"), 4))
    else:
        c2.metric("Delta(E2g-A1g)", _fmt(row.get("delta_e2g_a1g"), 2))
    c3.metric("RMSE", _fmt(row.get("rmse"), 3))
    c4.metric("AIC / BIC", f"{_fmt(row.get('aic'),1)} / {_fmt(row.get('bic'),1)}")

    peak_rows: list[dict[str, str]] = []
    unit_label = "eV" if is_pl else "cm^-1"
    peak_keys = (
        [("i1", "I1"), ("i2", "I2"), ("a_minus", "A-"), ("a0", "A0"), ("b", "B"), ("pl", "PL")]
        if is_pl
        else [("lo", "LO"), ("e2g", "E2g"), ("a1g", "A1g"), ("zo", "ZO"), ("la", "LA")]
    )
    for key, label in peak_keys:
        pos = row.get(f"{key}_position")
        if pos is None:
            continue
        peak_rows.append(
            {
                "Peak": label,
                f"Position ({unit_label})": _fmt(pos, 4 if is_pl else 2),
                f"FWHM ({unit_label})": _fmt(row.get(f"{key}_fwhm"), 4 if is_pl else 2),
                "Flag": _fwhm_warn(row.get(f"{key}_fwhm")),
            }
        )

    if peak_rows:
        st.caption("Peak Parameters")
        st.dataframe(peak_rows, width="stretch", hide_index=True)

    aux_lines = []
    if is_pl:
        aux_lines.extend(
            [
                f"- Temperature: {row.get('temperature_k', 'NA')} K",
                f"- Treatment: {row.get('treatment_label', 'NA')}",
                f"- A-/A0 area ratio: {_fmt(row.get('a_minus_a0_area_ratio'), 3)}",
                f"- A0 fraction of A total: {_fmt(row.get('a0_fraction_of_a_total'), 3)}",
            ]
        )
    else:
        aux_lines.append(f"- Si calibration offset: {_fmt(row.get('calibration_offset'),4)} (success={row.get('calibration_success')})")
    aux_lines.extend([
        f"- Fit status: {row.get('fit_status', 'valid')}",
        f"- Decision: {row.get('review_decision', 'auto')}",
    ])
    st.markdown("\n".join(aux_lines))

    fit_status = str(row.get("fit_status", "valid")).strip().lower()
    if fit_status == "invalid":
        reasons = row.get("invalid_reasons", [])
        if not isinstance(reasons, list):
            reasons = [str(reasons)]
        st.error("Invalid fit: " + ", ".join(str(r) for r in reasons if str(r).strip()))

    if bool(row.get("needs_attention", False)):
        flags = row.get("quality_flags", [])
        if not isinstance(flags, list):
            flags = [str(flags)]
        st.warning("Attention required: " + ", ".join(str(f) for f in flags))

    st.download_button(
        "Download this spectrum row (JSON)",
        data=json.dumps(row, indent=2).encode("utf-8"),
        file_name=f"{str(row.get('spectrum_id', 'spectrum')).replace(':', '_')}.json",
        mime="application/json",
        key=download_key,
    )


