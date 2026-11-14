"""Spectrum-level plotting and helpers for raw/fitted overlays."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import plotly.graph_objects as go
import streamlit as st
from lmfit.models import GaussianModel, LorentzianModel, PseudoVoigtModel

from fitting.mos2_pl.run_raw_pipeline import NM_TO_EV
from labkit.plot_theme import LEGEND_RIGHT

from . import graph_style
from .figure_sizes import show
from .spectrum_view import default_view_range, view_window

# Which peaks exist and how they are drawn. Colours and line styles are in raman_graph.yaml
# (all_spectra_viewer.style); nothing here repeats them.
_PEAKS: dict[str, dict[str, Any]] = {
    "pl": {"label": "PL", "fill": True},
    "i1": {"label": "I1", "fill": True},
    "i2": {"label": "I2", "fill": True},
    "a_minus": {"label": "A-", "fill": True},
    "a0": {"label": "A0", "fill": True},
    "b": {"label": "B", "fill": True},
    "lo": {"label": "LO", "fill": True},
    "e2g": {"label": "E2g", "fill": False},
    "a1g": {"label": "A1g", "fill": False},
    "zo": {"label": "ZO", "fill": True},
    "la": {"label": "LA", "fill": True},
}

_STYLE_PATH = "raman_graph.all_spectra_viewer.style"
_STYLE_TEXT_KEYS = ("raw_marker_color", "fit_line_color", "baseline_color", "baseline_dash", "component_line_dash")
_STYLE_NUMBER_KEYS = (
    "raw_marker_size",
    "raw_marker_opacity",
    "fit_line_width",
    "baseline_width",
    "component_line_width",
    "component_fill_alpha",
)


def resolve_source_file(source_value: Any, project_root: Path) -> Path | None:
    if not isinstance(source_value, str) or not source_value.strip():
        return None
    normalized = source_value.strip().replace("\\", "/")
    for raw_str in (source_value.strip(), normalized):
        candidate = Path(raw_str)
        if candidate.is_absolute() and candidate.exists():
            return candidate
        rel_candidate = project_root / candidate
        if rel_candidate.exists():
            return rel_candidate

    lower_norm = normalized.lower()
    marker = "data/raw/"
    idx = lower_norm.find(marker)
    if idx != -1:
        subpath = normalized[idx:]
        fallback_candidate = project_root / Path(subpath)
        if fallback_candidate.exists():
            return fallback_candidate
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


def _required(mapping: Any, key: str, path: str) -> Any:
    if not isinstance(mapping, dict) or key not in mapping:
        raise KeyError(f"{path}.{key} is missing in the graph config")
    return mapping[key]


def _resolve_overlay_style(style_cfg: dict[str, Any] | None) -> dict[str, Any]:
    """Line and marker style of the spectrum figure, read from the graph config without code-side defaults."""
    source = style_cfg if isinstance(style_cfg, dict) and style_cfg else graph_style.overlay_style_cfg()
    style: dict[str, Any] = {key: str(_required(source, key, _STYLE_PATH)).strip() for key in _STYLE_TEXT_KEYS}
    for key in _STYLE_NUMBER_KEYS:
        style[key] = float(_required(source, key, _STYLE_PATH))
    colors = _required(source, "component_colors", _STYLE_PATH)
    style["component_colors"] = {
        key: str(_required(colors, key, f"{_STYLE_PATH}.component_colors")).strip() for key in _PEAKS
    }
    style["raw_marker_opacity"] = float(np.clip(style["raw_marker_opacity"], 0.0, 1.0))
    style["component_fill_alpha"] = float(np.clip(style["component_fill_alpha"], 0.0, 1.0))
    style["raw_marker_size"] = max(1, int(style["raw_marker_size"]))
    return style


def _resolve_fit_curve_cfg(fit_curve_cfg: dict[str, Any] | None) -> dict[str, Any]:
    """How densely the fitted curve is drawn, read from the graph config."""
    source = fit_curve_cfg if isinstance(fit_curve_cfg, dict) and fit_curve_cfg else graph_style.fit_curve_cfg()
    path = "raman_graph.all_spectra_viewer.fit_curve"
    return {
        "smooth_factor": max(1, int(_required(source, "smooth_factor", path))),
        "max_points": max(32, int(_required(source, "max_points", path))),
    }


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
    pl_c = _to_float(row.get("pl_position")) if modality != "raman" else float("nan")

    if x_view_min is None or x_view_max is None:
        x_view_min, x_view_max = default_view_range(
            x, row, "pl" if np.isfinite(pl_c) else "raman", view_window(graph_style.load_raman_graph_config_file())
        )

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

    peak_style = {key: {**values, "color": style["component_colors"][key]} for key, values in _PEAKS.items()}

    pl_component_keys = ("i1", "i2", "a_minus", "a0", "b")
    has_explicit_pl_components = any(np.isfinite(_to_float(row.get(f"{key}_position"))) for key in pl_component_keys)
    used_component_approx = False
    component_sum_dense = np.zeros_like(x_dense, dtype=float)
    component_count = 0
    for key, peak_info in peak_style.items():
        if modality == "raman" and key in {"i1", "i2", "a_minus", "a0", "b", "pl"}:
            continue
        if modality == "pl" and key in {"lo", "e2g", "a1g", "zo", "la"}:
            continue
        if key == "pl" and has_explicit_pl_components:
            continue
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

    is_pl = modality == "pl" or (modality != "raman" and np.isfinite(pl_c))
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
        title=title,
        xaxis_title=xaxis_title,
        yaxis_title="Intensity (a.u.)",
        hovermode="x unified",
        legend=LEGEND_RIGHT,  # many entries: outside, so that no peak is covered
        margin={"l": 60, "r": 220, "t": 60, "b": 60},
    )
    show(fig, "spectrum", filename=str(spectrum_id))

    if used_component_approx:
        st.info("This row was plotted with component approximation (legacy report without area/sigma/fraction).")


def render_fit_summary(
    row: dict[str, Any],
    *,
    download_key: str | None = None,
    fwhm_warn_cfg: dict[str, float],
) -> None:
    # Plausible FWHM ranges from science_settings.fwhm_warn_limits (config.yaml `fwhm_warn`).
    raman_fwhm_min = fwhm_warn_cfg["raman_min"]
    raman_fwhm_max = fwhm_warn_cfg["raman_max"]
    pl_fwhm_max = fwhm_warn_cfg["pl_max"]

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
            return "(!)" if (f <= 0.0 or f >= pl_fwhm_max) else ""
        return "(!)" if (f < raman_fwhm_min or f >= raman_fwhm_max) else ""

    modality = str(row.get("modality", "")).strip().lower()
    is_pl = modality == "pl" or (modality != "raman" and "pl_position" in row)

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


