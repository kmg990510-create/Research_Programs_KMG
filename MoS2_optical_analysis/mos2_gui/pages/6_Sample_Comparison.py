"""Page for cross-sample comparison plots (LO features excluded)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(BOOTSTRAP_ROOT) not in sys.path:
    sys.path.append(str(BOOTSTRAP_ROOT))

from fitting.mos2_core.core.runtime_paths import runtime_project_root  # noqa: E402
from fitting.mos2_core.review.manual_overrides import override_mtime_ns_for_report  # noqa: E402

ROOT = runtime_project_root(__file__, 2)
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from labkit.chrome import panel_title  # noqa: E402
from mos2_gui.components import report_loader as _report_loader  # noqa: E402
from mos2_gui.components.chrome import render_mos2_chrome  # noqa: E402
from mos2_gui.components.figure_sizes import figure_settings_popover, show  # noqa: E402
from mos2_gui.components.map_figure import default_colorbar_title  # noqa: E402
from labkit.plot_theme import (  # noqa: E402
    AUX,
    CATEGORICAL,
    ERRORBAR_CAP,
    ERRORBAR_WIDTH,
    INK,
    LINE_AUX,
    LINE_DATA,
    MARKER_CENTER,
    MARKER_ON_LINE,
    MARKER_RAW,
    OUTLINE,
    SEQUENTIAL,
    categorical_colors,
)
from mos2_gui.components.scatter_style import (  # noqa: E402
    LEGEND_POSITIONS,
    TICK_DIRECTIONS,
    ScatterStyle,
    apply_scatter_style,
)
from mos2_gui.components.derived_parameters import strain_doping  # noqa: E402
from mos2_gui.components.science_settings import strain_doping_settings  # noqa: E402

list_report_json_files = _report_loader.list_report_json_files
load_spectra_dataframe = _report_loader.load_spectra_dataframe
load_graph_config = getattr(_report_loader, "load_graph_config", lambda: {})
render_status_rejected_filters = _report_loader.render_status_rejected_filters

DOPING_N_AXIS_LABEL = "Doping n (10^13 cm^-2)"


def _clean_sample_name(path: Path) -> str:
    name = path.stem
    for suffix in ("_fit_report", "_summary"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _unique_label(base: str, used: set[str]) -> str:
    if base not in used:
        used.add(base)
        return base
    idx = 2
    while f"{base} ({idx})" in used:
        idx += 1
    label = f"{base} ({idx})"
    used.add(label)
    return label


def _to_numeric(df: pd.DataFrame, col: str) -> np.ndarray:
    if col not in df.columns:
        return np.array([], dtype=float)
    return pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)


def _extract_vectors(df: pd.DataFrame, cols: list[str]) -> list[np.ndarray]:
    if df.empty:
        return [np.array([], dtype=float) for _ in cols]
    arrays = [_to_numeric(df, col) for col in cols]
    if not arrays or any(arr.size == 0 for arr in arrays):
        return [np.array([], dtype=float) for _ in cols]
    valid_mask = np.ones(arrays[0].shape[0], dtype=bool)
    for arr in arrays:
        valid_mask &= np.isfinite(arr)
    return [arr[valid_mask] for arr in arrays]


def _center(values: np.ndarray, how: str) -> float:
    if values.size == 0:
        return float("nan")
    if how == "mean":
        return float(np.mean(values))
    return float(np.median(values))


def _error(values: np.ndarray, how: str) -> float:
    if values.size <= 1:
        return float("nan")
    if how == "std":
        return float(np.std(values, ddof=1))
    if how == "sem":
        return float(np.std(values, ddof=1) / np.sqrt(values.size))
    if how == "mad":
        med = np.median(values)
        return float(1.4826 * np.median(np.abs(values - med)))
    if how == "iqr":
        q25, q75 = np.percentile(values, [25, 75])
        return float((q75 - q25) / 2.0)
    return float("nan")


def _is_pl_frame(frame: pd.DataFrame) -> bool:
    if frame.empty:
        return False
    if "modality" in frame.columns:
        modalities = frame["modality"].astype(str).str.lower()
        if modalities.eq("pl").any():
            return True
        if modalities.eq("raman").any():
            return False
    return any(col in frame.columns for col in ("a_minus_position", "a0_position", "pl_position"))


def _temperature_from_row(row: pd.Series) -> float | None:
    value = row.get("temperature_k")
    try:
        number = float(value)
        if np.isfinite(number):
            return number
    except (TypeError, ValueError):
        pass
    source = str(row.get("source_file", ""))
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*K(?![A-Za-z])", source, flags=re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def _treatment_from_row(row: pd.Series, sample_name: str) -> str:
    for value in (row.get("treatment_label"), sample_name, row.get("source_file")):
        text = str(value or "")
        lower = text.lower()
        if "pristine" in lower:
            return "Pristine"
        if "treatment" in lower:
            return "Treatment"
        if "4atp" in lower or "atp" in lower:
            return "4ATP"
    return sample_name


def _infer_report_modality(path: Path) -> str:
    parent_mod = path.parent.parent.name.strip().lower()
    if parent_mod in {"raman", "pl"}:
        return parent_mod
    lower_name = path.name.lower()
    if lower_name.startswith("pl_") or "_pl_" in lower_name:
        return "pl"
    return "raman"


def _render_pl_comparison(
    sample_frames: dict[str, pd.DataFrame],
    color_map: dict[str, str] | None = None,
    center_metric: str = "mean",
    error_metric: str = "std",
    overlay_scatter: bool = True,
    scatter_style: ScatterStyle | None = None,
) -> None:
    metric_candidates = [
        "a_minus_position",
        "a0_position",
        "a_minus_a0_energy_split",
        "a_minus_a0_area_ratio",
        "a0_fraction_of_a_total",
        "b_to_a_total_area_ratio",
        "defect_to_a_total_area_ratio",
        "a_minus_fwhm",
        "a0_fwhm",
        "b_position",
        "i1_position",
        "i2_position",
        "pl_position",
        "pl_fwhm",
        "pl_area",
        "pl_height",
        "rmse",
        "r2",
    ]
    colors = color_map or {name: CATEGORICAL[i % len(CATEGORICAL)] for i, name in enumerate(sample_frames)}

    rows: list[pd.DataFrame] = []
    for sample_name, frame in sample_frames.items():
        work = frame.copy()
        work["sample"] = sample_name
        work["temperature_k"] = work.apply(_temperature_from_row, axis=1)
        work["treatment_label"] = work.apply(lambda row: _treatment_from_row(row, sample_name), axis=1)
        rows.append(work)
    combined = pd.concat(rows, ignore_index=True)

    available_metrics = [
        col
        for col in metric_candidates
        if col in combined.columns and pd.to_numeric(combined[col], errors="coerce").notna().any()
    ]
    if not available_metrics:
        st.warning("No PL comparison metrics found in the selected reports.")
        return

    st.subheader("Cross-Sample PL Summary")
    summary_rows: list[dict[str, object]] = []
    for sample_name, frame in sample_frames.items():
        s_row: dict[str, object] = {"sample": sample_name, "n_spectra": len(frame)}
        for metric in available_metrics:
            vals = _to_numeric(frame, metric)
            vals = vals[np.isfinite(vals)]
            if vals.size:
                s_row[f"{metric}_{center_metric}"] = _center(vals, center_metric)
                s_row[f"{metric}_{error_metric}"] = _error(vals, error_metric)
        summary_rows.append(s_row)
    if summary_rows:
        st.dataframe(pd.DataFrame(summary_rows), width="stretch", hide_index=True)

    if len(available_metrics) >= 2:
        st.subheader("Cross-Sample PL Scatter & Error Bar Comparison")
        default_x = "a_minus_position" if "a_minus_position" in available_metrics else (
            "pl_position" if "pl_position" in available_metrics else available_metrics[0]
        )
        default_y = "a0_position" if "a0_position" in available_metrics and default_x != "a0_position" else (
            "a_minus_a0_area_ratio" if "a_minus_a0_area_ratio" in available_metrics and default_x != "a_minus_a0_area_ratio" else (
                "pl_fwhm" if "pl_fwhm" in available_metrics and default_x != "pl_fwhm" else available_metrics[min(1, len(available_metrics) - 1)]
            )
        )
        xy_cols = st.columns(2)
        pl_x_metric = xy_cols[0].selectbox(
            "X metric",
            options=available_metrics,
            index=available_metrics.index(default_x),
            key="pl_cmp_x_metric",
        )
        pl_y_metric = xy_cols[1].selectbox(
            "Y metric",
            options=available_metrics,
            index=available_metrics.index(default_y),
            key="pl_cmp_y_metric",
        )
        pair_data: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for sample_name, frame in sample_frames.items():
            xv, yv = _extract_vectors(frame, [pl_x_metric, pl_y_metric])
            if xv.size and yv.size:
                pair_data[sample_name] = (xv, yv)
        if pair_data:
            x_axis_title = default_colorbar_title(pl_x_metric, "pl")
            y_axis_title = default_colorbar_title(pl_y_metric, "pl")
            c_left, c_right = st.columns(2)
            with c_left:
                fig_sc = _build_scatter_figure(
                    pair_data,
                    colors,
                    f"{pl_x_metric} vs {pl_y_metric} (Scatter)",
                    x_axis_title,
                    y_axis_title,
                )
                if scatter_style is not None:
                    apply_scatter_style(fig_sc, scatter_style)
                show(fig_sc, "sample_pl", filename=f"pl_{pl_x_metric}_vs_{pl_y_metric}_scatter")
            with c_right:
                fig_eb = _build_errorbar_figure(
                    pair_data,
                    colors,
                    f"{pl_x_metric} vs {pl_y_metric} ({center_metric} +/- {error_metric})",
                    x_axis_title,
                    y_axis_title,
                    center_metric,
                    error_metric,
                    overlay_scatter,
                )
                if scatter_style is not None:
                    apply_scatter_style(fig_eb, scatter_style)
                show(fig_eb, "sample_pl", filename=f"pl_{pl_x_metric}_vs_{pl_y_metric}_errorbar")

    temp_df = combined[pd.to_numeric(combined["temperature_k"], errors="coerce").notna()].copy()
    if temp_df.empty:
        return

    temp_df["temperature_k"] = pd.to_numeric(temp_df["temperature_k"], errors="coerce")
    st.subheader("PL Temperature / Treatment Comparison")
    selected_metric = st.selectbox("PL metric vs Temperature", options=available_metrics, index=0)
    plot_df = temp_df[["sample", "treatment_label", "temperature_k", selected_metric]].copy()
    plot_df[selected_metric] = pd.to_numeric(plot_df[selected_metric], errors="coerce")
    plot_df = plot_df.dropna(subset=["temperature_k", selected_metric])

    agg_rows: list[dict[str, object]] = []
    for (treat_lbl, temp_val), grp in plot_df.groupby(["treatment_label", "temperature_k"], dropna=False):
        vals = grp[selected_metric].to_numpy(dtype=float)
        vals = vals[np.isfinite(vals)]
        if vals.size == 0:
            continue
        c_val = _center(vals, center_metric)
        e_val = _error(vals, error_metric)
        agg_rows.append(
            {
                "treatment_label": str(treat_lbl),
                "temperature_k": float(temp_val),
                selected_metric: float(c_val),
                "error_val": float(e_val) if np.isfinite(e_val) and vals.size > 1 else 0.0,
                "sample": ", ".join(sorted(set(grp["sample"].astype(str)))),
                "n_points": int(vals.size),
            }
        )
    agg_df = pd.DataFrame(agg_rows).sort_values(["treatment_label", "temperature_k"]) if agg_rows else plot_df
    treat_colors = categorical_colors(agg_df["treatment_label"]) if "treatment_label" in agg_df.columns else {}
    fig = px.line(
        agg_df,
        x="temperature_k",
        y=selected_metric,
        error_y="error_val" if "error_val" in agg_df.columns and (agg_df["error_val"] > 0).any() else None,
        color="treatment_label",
        color_discrete_map=treat_colors,
        markers=True,
        hover_data=[c for c in ["sample", "n_points"] if c in agg_df.columns],
    )
    fig.update_traces(line={"width": LINE_DATA}, marker={"size": MARKER_ON_LINE})
    fig.update_layout(
        xaxis_title="Temperature (K)",
        yaxis_title=default_colorbar_title(selected_metric, "pl"),
    )
    if scatter_style is not None:
        apply_scatter_style(fig, scatter_style)
    show(fig, "sample_pl", filename=f"pl_{selected_metric}_vs_temperature")

    table_cols = ["sample", "treatment_label", "temperature_k", *available_metrics]
    st.dataframe(
        temp_df[table_cols].sort_values(["temperature_k", "treatment_label"]),
        width="stretch",
        hide_index=True,
    )

    pair_metrics = [
        metric
        for metric in [
            "a_minus_position",
            "a0_position",
            "a_minus_a0_area_ratio",
            "a0_fraction_of_a_total",
            "a_minus_fwhm",
            "a0_fwhm",
            "b_to_a_total_area_ratio",
            "defect_to_a_total_area_ratio",
        ]
        if metric in available_metrics
    ]
    labels = set(temp_df["treatment_label"].astype(str))
    if {"Pristine", "Treatment"}.issubset(labels) and pair_metrics:
        paired_rows: list[dict[str, float | str]] = []
        for temp, group in temp_df.groupby("temperature_k"):
            pristine = group[group["treatment_label"].astype(str) == "Pristine"]
            treatment = group[group["treatment_label"].astype(str) == "Treatment"]
            if pristine.empty or treatment.empty:
                continue
            out: dict[str, float | str] = {"temperature_k": float(temp)}
            for metric in pair_metrics:
                p_vals = _to_numeric(pristine, metric)
                t_vals = _to_numeric(treatment, metric)
                p_vals = p_vals[np.isfinite(p_vals)]
                t_vals = t_vals[np.isfinite(t_vals)]
                if p_vals.size and t_vals.size:
                    p_val = _center(p_vals, center_metric)
                    t_val = _center(t_vals, center_metric)
                    if np.isfinite(p_val) and np.isfinite(t_val):
                        out[f"{metric}_treatment_minus_pristine"] = float(t_val - p_val)
            paired_rows.append(out)
        if paired_rows:
            st.subheader("Matched Treatment - Pristine")
            st.dataframe(pd.DataFrame(paired_rows).sort_values("temperature_k"), width="stretch", hide_index=True)


def _compute_eps_n(
    e2g: np.ndarray,
    a1g: np.ndarray,
    omega_e0: float,
    omega_a0: float,
    s_e: float,
    s_a: float,
    d_e: float,
    d_a: float,
) -> tuple[np.ndarray, np.ndarray]:
    eps, n = strain_doping(e2g, a1g, omega_e0, omega_a0, {"s_e": s_e, "s_a": s_a, "d_e": d_e, "d_a": d_a})
    return eps, n


def _collect_eps_n(
    samples: dict[str, pd.DataFrame],
    omega_e0: float,
    omega_a0: float,
    s_e: float,
    s_a: float,
    d_e: float,
    d_a: float,
) -> tuple[dict[str, tuple[np.ndarray, np.ndarray]], np.ndarray, np.ndarray]:
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    eps_all: list[np.ndarray] = []
    n_all: list[np.ndarray] = []
    for label, frame in samples.items():
        e2g, a1g = _extract_vectors(frame, ["e2g_position", "a1g_position"])
        if e2g.size == 0:
            continue
        eps, n = _compute_eps_n(e2g, a1g, omega_e0, omega_a0, s_e, s_a, d_e, d_a)
        mask = np.isfinite(eps) & np.isfinite(n)
        eps = eps[mask]
        n = n[mask]
        if eps.size and n.size:
            out[label] = (eps, n)
            eps_all.append(eps)
            n_all.append(n)
    return (
        out,
        np.concatenate(eps_all) if eps_all else np.array([], dtype=float),
        np.concatenate(n_all) if n_all else np.array([], dtype=float),
    )


def _collect_n_vs_fwhm(
    samples: dict[str, pd.DataFrame],
    fwhm_col: str,
    omega_e0: float,
    omega_a0: float,
    s_e: float,
    s_a: float,
    d_e: float,
    d_a: float,
) -> tuple[dict[str, tuple[np.ndarray, np.ndarray]], np.ndarray, np.ndarray]:
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    n_all: list[np.ndarray] = []
    fwhm_all: list[np.ndarray] = []
    for label, frame in samples.items():
        e2g, a1g, fwhm = _extract_vectors(frame, ["e2g_position", "a1g_position", fwhm_col])
        if e2g.size == 0:
            continue
        _, n = _compute_eps_n(e2g, a1g, omega_e0, omega_a0, s_e, s_a, d_e, d_a)
        mask = np.isfinite(n) & np.isfinite(fwhm)
        n = n[mask]
        fwhm = fwhm[mask]
        if n.size and fwhm.size:
            out[label] = (n, fwhm)
            n_all.append(n)
            fwhm_all.append(fwhm)
    return (
        out,
        np.concatenate(n_all) if n_all else np.array([], dtype=float),
        np.concatenate(fwhm_all) if fwhm_all else np.array([], dtype=float),
    )


def _collect_absolute_positions(
    samples: dict[str, pd.DataFrame],
) -> tuple[dict[str, tuple[np.ndarray, np.ndarray]], np.ndarray, np.ndarray]:
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    e2g_all: list[np.ndarray] = []
    a1g_all: list[np.ndarray] = []
    for label, frame in samples.items():
        e2g, a1g = _extract_vectors(frame, ["e2g_position", "a1g_position"])
        if e2g.size and a1g.size:
            out[label] = (e2g, a1g)
            e2g_all.append(e2g)
            a1g_all.append(a1g)
    return (
        out,
        np.concatenate(e2g_all) if e2g_all else np.array([], dtype=float),
        np.concatenate(a1g_all) if a1g_all else np.array([], dtype=float),
    )


def _collect_fwhm_pair(
    samples: dict[str, pd.DataFrame],
) -> tuple[dict[str, tuple[np.ndarray, np.ndarray]], np.ndarray, np.ndarray]:
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    e2g_all: list[np.ndarray] = []
    a1g_all: list[np.ndarray] = []
    for label, frame in samples.items():
        e2g, a1g = _extract_vectors(frame, ["e2g_fwhm", "a1g_fwhm"])
        if e2g.size and a1g.size:
            out[label] = (e2g, a1g)
            e2g_all.append(e2g)
            a1g_all.append(a1g)
    return (
        out,
        np.concatenate(e2g_all) if e2g_all else np.array([], dtype=float),
        np.concatenate(a1g_all) if a1g_all else np.array([], dtype=float),
    )


def _safe_ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    out = np.full_like(numerator, np.nan, dtype=float)
    mask = np.isfinite(numerator) & np.isfinite(denominator) & (denominator != 0.0)
    out[mask] = numerator[mask] / denominator[mask]
    out[~np.isfinite(out)] = np.nan
    return out


def _resolve_lo_ratio_vector(frame: pd.DataFrame) -> tuple[np.ndarray, str]:
    n_rows = len(frame)
    if n_rows == 0:
        return np.array([], dtype=float), "missing"

    lo_area = _to_numeric(frame, "lo_area")
    a1g_area = _to_numeric(frame, "a1g_area")
    lo_height = _to_numeric(frame, "lo_height")
    a1g_height = _to_numeric(frame, "a1g_height")

    area_ratio = np.full(n_rows, np.nan, dtype=float)
    height_ratio = np.full(n_rows, np.nan, dtype=float)

    has_area_cols = lo_area.size == n_rows and a1g_area.size == n_rows
    has_height_cols = lo_height.size == n_rows and a1g_height.size == n_rows

    if has_area_cols:
        area_ratio = _safe_ratio(lo_area, a1g_area)
    if has_height_cols:
        height_ratio = _safe_ratio(lo_height, a1g_height)

    area_valid = int(np.isfinite(area_ratio).sum())
    height_valid = int(np.isfinite(height_ratio).sum())

    if area_valid > 0:
        ratio = area_ratio.copy()
        source = "area"
        if height_valid > 0:
            fill_mask = np.isnan(ratio) & np.isfinite(height_ratio)
            if bool(np.any(fill_mask)):
                ratio[fill_mask] = height_ratio[fill_mask]
                source = "area+height_fallback"
        return ratio, source

    if height_valid > 0:
        return height_ratio, "height_fallback"

    return np.full(n_rows, np.nan, dtype=float), "missing"


def _collect_lo_ratio_vs_n(
    samples: dict[str, pd.DataFrame],
    omega_e0: float,
    omega_a0: float,
    s_e: float,
    s_a: float,
    d_e: float,
    d_a: float,
) -> tuple[dict[str, tuple[np.ndarray, np.ndarray]], np.ndarray, np.ndarray, dict[str, str]]:
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    n_all: list[np.ndarray] = []
    ratio_all: list[np.ndarray] = []
    ratio_source_by_sample: dict[str, str] = {}
    for label, frame in samples.items():
        e2g, a1g = _extract_vectors(frame, ["e2g_position", "a1g_position"])
        if e2g.size == 0:
            continue

        ratio, ratio_source = _resolve_lo_ratio_vector(frame)
        if ratio.size != len(frame):
            continue

        e2g_full = _to_numeric(frame, "e2g_position")
        a1g_full = _to_numeric(frame, "a1g_position")
        if e2g_full.size != len(frame) or a1g_full.size != len(frame):
            continue

        eps, n = _compute_eps_n(e2g_full, a1g_full, omega_e0, omega_a0, s_e, s_a, d_e, d_a)
        mask = np.isfinite(n) & np.isfinite(ratio)
        n_vec = n[mask]
        ratio_vec = ratio[mask]
        if n_vec.size and ratio_vec.size:
            out[label] = (n_vec, ratio_vec)
            n_all.append(n_vec)
            ratio_all.append(ratio_vec)
            ratio_source_by_sample[label] = ratio_source

    return (
        out,
        np.concatenate(n_all) if n_all else np.array([], dtype=float),
        np.concatenate(ratio_all) if ratio_all else np.array([], dtype=float),
        ratio_source_by_sample,
    )


def _collect_lo_ratio_vs_eps(
    samples: dict[str, pd.DataFrame],
    omega_e0: float,
    omega_a0: float,
    s_e: float,
    s_a: float,
    d_e: float,
    d_a: float,
) -> tuple[dict[str, tuple[np.ndarray, np.ndarray]], np.ndarray, np.ndarray, dict[str, str]]:
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    eps_all: list[np.ndarray] = []
    ratio_all: list[np.ndarray] = []
    ratio_source_by_sample: dict[str, str] = {}
    for label, frame in samples.items():
        ratio, ratio_source = _resolve_lo_ratio_vector(frame)
        if ratio.size != len(frame):
            continue

        e2g_full = _to_numeric(frame, "e2g_position")
        a1g_full = _to_numeric(frame, "a1g_position")
        if e2g_full.size != len(frame) or a1g_full.size != len(frame):
            continue

        eps, _ = _compute_eps_n(e2g_full, a1g_full, omega_e0, omega_a0, s_e, s_a, d_e, d_a)
        mask = np.isfinite(eps) & np.isfinite(ratio)
        eps_vec = eps[mask]
        ratio_vec = ratio[mask]
        if eps_vec.size and ratio_vec.size:
            out[label] = (eps_vec, ratio_vec)
            eps_all.append(eps_vec)
            ratio_all.append(ratio_vec)
            ratio_source_by_sample[label] = ratio_source
    return (
        out,
        np.concatenate(eps_all) if eps_all else np.array([], dtype=float),
        np.concatenate(ratio_all) if ratio_all else np.array([], dtype=float),
        ratio_source_by_sample,
    )


def _collect_lo_ratio_vs_fwhm(
    samples: dict[str, pd.DataFrame],
    fwhm_col: str,
) -> tuple[dict[str, tuple[np.ndarray, np.ndarray]], np.ndarray, np.ndarray, dict[str, str]]:
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    ratio_all: list[np.ndarray] = []
    fwhm_all: list[np.ndarray] = []
    ratio_source_by_sample: dict[str, str] = {}
    for label, frame in samples.items():
        ratio, ratio_source = _resolve_lo_ratio_vector(frame)
        fwhm = _to_numeric(frame, fwhm_col)
        if ratio.size != len(frame) or fwhm.size != len(frame):
            continue
        mask = np.isfinite(ratio) & np.isfinite(fwhm)
        ratio_vec = ratio[mask]
        fwhm_vec = fwhm[mask]
        if ratio_vec.size and fwhm_vec.size:
            out[label] = (ratio_vec, fwhm_vec)
            ratio_all.append(ratio_vec)
            fwhm_all.append(fwhm_vec)
            ratio_source_by_sample[label] = ratio_source
    return (
        out,
        np.concatenate(ratio_all) if ratio_all else np.array([], dtype=float),
        np.concatenate(fwhm_all) if fwhm_all else np.array([], dtype=float),
        ratio_source_by_sample,
    )


def _build_lo_ratio_heatmap(sample_name: str, frame: pd.DataFrame, use_log10: bool) -> go.Figure | None:
    required = {"map_x", "map_y"}
    if not required.issubset(frame.columns):
        return None
    ratio, _ = _resolve_lo_ratio_vector(frame)
    if ratio.size != len(frame):
        return None

    ratio_df = frame.copy()
    ratio_df["lo_ratio"] = ratio
    ratio_df["map_x"] = pd.to_numeric(ratio_df["map_x"], errors="coerce")
    ratio_df["map_y"] = pd.to_numeric(ratio_df["map_y"], errors="coerce")
    ratio_df = ratio_df.dropna(subset=["map_x", "map_y", "lo_ratio"])
    if ratio_df.empty:
        return None

    pivot = (
        ratio_df.pivot_table(index="map_y", columns="map_x", values="lo_ratio", aggfunc="mean")
        .sort_index(ascending=True)
        .sort_index(axis=1, ascending=True)
    )
    if pivot.empty:
        return None

    values = pivot.to_numpy(dtype=float)
    color_label = "LO_area / A1g_area"
    if use_log10:
        with np.errstate(divide="ignore", invalid="ignore"):
            values = np.log10(values)
        color_label = "log10(LO_area / A1g_area)"

    fig = px.imshow(
        values,
        x=pivot.columns.to_numpy(dtype=float),
        y=pivot.index.to_numpy(dtype=float),
        origin="lower",
        aspect="auto",
        color_continuous_scale=SEQUENTIAL,
        labels={"x": "X (point index)", "y": "Y (point index)", "color": color_label},
        title=f"LO ratio heatmap: {sample_name}",
    )
    return fig


def _build_scatter_figure(
    data: dict[str, tuple[np.ndarray, np.ndarray]],
    colors: dict[str, str],
    title: str,
    x_label: str,
    y_label: str,
    add_zero_lines: bool = False,
) -> go.Figure:
    fig = go.Figure()
    for sample, (x_vals, y_vals) in data.items():
        fig.add_trace(
            go.Scatter(
                x=x_vals,
                y=y_vals,
                mode="markers",
                name=sample,
                marker={"size": MARKER_RAW, "opacity": 0.65, "color": colors[sample]},
            )
        )
    if add_zero_lines:
        fig.add_hline(y=0.0, line_width=LINE_AUX, line_dash="dot", line_color=AUX)
        fig.add_vline(x=0.0, line_width=LINE_AUX, line_dash="dot", line_color=AUX)
    fig.update_layout(
        title=title,
        xaxis_title=x_label,
        yaxis_title=y_label,
        legend_title="Sample",
    )
    return fig


def _build_errorbar_figure(
    data: dict[str, tuple[np.ndarray, np.ndarray]],
    colors: dict[str, str],
    title: str,
    x_label: str,
    y_label: str,
    center_metric: str,
    error_metric: str,
    overlay_scatter: bool,
    add_zero_lines: bool = False,
) -> go.Figure:
    fig = go.Figure()
    for sample, (x_vals, y_vals) in data.items():
        if overlay_scatter:
            fig.add_trace(
                go.Scatter(
                    x=x_vals,
                    y=y_vals,
                    mode="markers",
                    showlegend=False,
                    marker={"size": MARKER_RAW, "opacity": 0.35, "color": colors[sample]},
                    hovertemplate=f"{sample}<br>x=%{{x:.4f}}<br>y=%{{y:.4f}}<extra></extra>",
                )
            )

        cx, cy = _center(x_vals, center_metric), _center(y_vals, center_metric)
        ex, ey = _error(x_vals, error_metric), _error(y_vals, error_metric)
        fig.add_trace(
            go.Scatter(
                x=[cx],
                y=[cy],
                mode="markers",
                name=sample,
                marker={"size": MARKER_CENTER, "color": colors[sample], "line": {"width": OUTLINE, "color": INK}},
                error_x={
                    "type": "data",
                    "array": [ex if np.isfinite(ex) else 0.0],
                    "visible": bool(np.isfinite(ex)),
                    "thickness": ERRORBAR_WIDTH,
                    "width": ERRORBAR_CAP,
                    "color": INK,
                },
                error_y={
                    "type": "data",
                    "array": [ey if np.isfinite(ey) else 0.0],
                    "visible": bool(np.isfinite(ey)),
                    "thickness": ERRORBAR_WIDTH,
                    "width": ERRORBAR_CAP,
                    "color": INK,
                },
                hovertemplate=(
                    f"{sample}<br>center_x=%{{x:.4f}}<br>center_y=%{{y:.4f}}"
                    f"<br>{error_metric}_x={ex:.4f}<br>{error_metric}_y={ey:.4f}<extra></extra>"
                ),
            )
        )
    if add_zero_lines:
        fig.add_hline(y=0.0, line_width=LINE_AUX, line_dash="dot", line_color=AUX)
        fig.add_vline(x=0.0, line_width=LINE_AUX, line_dash="dot", line_color=AUX)
    fig.update_layout(
        title=title,
        xaxis_title=x_label,
        yaxis_title=y_label,
        legend_title="Sample",
    )
    return fig


def _add_absolute_isolines(
    fig: go.Figure,
    omega_e0: float,
    omega_a0: float,
    s_e: float,
    s_a: float,
    d_e: float,
    d_a: float,
    eps_step: float,
    n_step: float,
    eps_range: tuple[float, float],
    n_range: tuple[float, float],
) -> None:
    eps_vals = np.arange(eps_range[0], eps_range[1] + 1e-9, max(eps_step, 0.05))
    n_vals = np.arange(n_range[0], n_range[1] + 1e-9, max(n_step, 0.05))
    n_line = np.linspace(float(n_vals.min()), float(n_vals.max()), 250)
    e_line = np.linspace(float(eps_vals.min()), float(eps_vals.max()), 250)

    for eps in eps_vals:
        d_e2g = s_e * eps + d_e * n_line
        d_a1g = s_a * eps + d_a * n_line
        fig.add_trace(
            go.Scatter(
                x=omega_e0 + d_e2g,
                y=omega_a0 + d_a1g,
                mode="lines",
                opacity=0.45,
                showlegend=False,
                hoverinfo="skip",
                line={"dash": "dash", "width": LINE_AUX, "color": AUX},
            )
        )

    for n_val in n_vals:
        d_e2g = s_e * e_line + d_e * n_val
        d_a1g = s_a * e_line + d_a * n_val
        fig.add_trace(
            go.Scatter(
                x=omega_e0 + d_e2g,
                y=omega_a0 + d_a1g,
                mode="lines",
                opacity=0.45,
                showlegend=False,
                hoverinfo="skip",
                line={"dash": "dot", "width": LINE_AUX, "color": AUX},
            )
        )


def _auto_axis_range(values: np.ndarray, pad_ratio: float = 0.12, min_span: float = 0.8) -> list[float] | None:
    if values.size == 0:
        return None
    vmin = float(np.nanmin(values))
    vmax = float(np.nanmax(values))
    if not np.isfinite(vmin) or not np.isfinite(vmax):
        return None
    span = max(vmax - vmin, float(min_span))
    center = (vmax + vmin) / 2.0
    pad = span * float(pad_ratio)
    half = span / 2.0
    return [center - half - pad, center + half + pad]


render_mos2_chrome("Compare", "Sample Comparison · MoS2 Optical Analysis", compare_sub="Samples")
st.header("Sample Comparison")
st.caption("Cross-sample comparison plots derived from fit report outputs.")

graph_cfg = load_graph_config()
sample_cfg = graph_cfg.get("sample_comparison", {}) if isinstance(graph_cfg, dict) else {}
status_cfg = sample_cfg.get("status_filter", {}) if isinstance(sample_cfg, dict) else {}
isoline_cfg = sample_cfg.get("absolute_isolines", {}) if isinstance(sample_cfg, dict) else {}
isoline_steps_cfg = isoline_cfg.get("steps", {}) if isinstance(isoline_cfg, dict) else {}

# Strain/doping coefficients and isoline spans: strain (%), carrier density (1e13 cm^-2).
sd_settings = strain_doping_settings(graph_cfg)
coefficients = sd_settings["coefficients"]
isoline_eps_range = sd_settings["eps_range"]
isoline_n_range = sd_settings["n_range"]

report_files = list_report_json_files()
if not report_files:
    st.warning(
        "No report JSON files found in data/results/{raman,pl}/reports."
    )
    st.stop()

file_labels: dict[str, Path] = {}
modality_by_label: dict[str, str] = {}
for report in report_files:
    stamp = report.stat().st_mtime
    label = f"{report.name}  ({pd.to_datetime(stamp, unit='s').strftime('%Y-%m-%d %H:%M:%S')})"
    file_labels[label] = report
    modality_by_label[label] = _infer_report_modality(report)

available_modalities = sorted(set(modality_by_label.values()))
default_modality = _infer_report_modality(report_files[0]) if report_files else "raman"
status_options = ["valid", "attention", "invalid"]
status_default_raw = status_cfg.get("allowed_default", ["valid", "attention"])
if isinstance(status_default_raw, list):
    status_default = [str(v).strip().lower() for v in status_default_raw if str(v).strip().lower() in status_options]
else:
    status_default = ["valid", "attention"]
if not status_default:
    status_default = ["valid", "attention"]

report_store = st.session_state.setdefault("sample_cmp_report_store", {})
with st.container(border=True):
    panel_title("Reports to compare")
    if len(available_modalities) > 1:
        mod_options = ["raman", "pl", "all"]
        mod_key = "sample_cmp_modality_filter"
        if mod_key not in st.session_state or st.session_state[mod_key] not in mod_options:
            stored_mod = report_store.get("modality", default_modality)
            st.session_state[mod_key] = stored_mod if stored_mod in mod_options else mod_options[0]
        r_mod_col, r_sel_col = st.columns([1.4, 3.6], vertical_alignment="bottom")
        modality_choice = r_mod_col.radio(
            "Report modality",
            options=mod_options,
            horizontal=True,
            format_func=lambda m: m.upper() if m in {"pl"} else m.capitalize(),
            key=mod_key,
        )
        report_store["modality"] = modality_choice
    else:
        modality_choice = available_modalities[0] if available_modalities else "all"
        r_sel_col = st.container()

    candidate_labels = [
        lbl
        for lbl in file_labels
        if modality_choice == "all" or modality_by_label.get(lbl) == modality_choice
    ]
    if not candidate_labels:
        candidate_labels = list(file_labels.keys())
    default_mod = modality_by_label.get(candidate_labels[0], default_modality)
    default_labels = [lbl for lbl in candidate_labels if modality_by_label.get(lbl) == default_mod]
    default_count = min(max(int(sample_cfg.get("default_report_count", 4)), 1), len(default_labels))
    sel_key = "sample_cmp_selected_reports"
    prev_mod = report_store.get("applied_modality")
    if (
        sel_key not in st.session_state
        or prev_mod != modality_choice
        or any(lbl not in candidate_labels for lbl in st.session_state.get(sel_key, []))
    ):
        stored_sel = [lbl for lbl in report_store.get("selected", []) if lbl in candidate_labels]
        st.session_state[sel_key] = stored_sel if (stored_sel and prev_mod == modality_choice) else default_labels[:default_count]
    selected_file_labels = r_sel_col.multiselect(
        "Reports to compare",
        options=candidate_labels,
        key=sel_key,
    )
    report_store["applied_modality"] = modality_choice
    report_store["selected"] = list(selected_file_labels)

status_filter_on, status_selected, hide_rejected = render_status_rejected_filters(
    pd.DataFrame(columns=["fit_status", "review_decision"]),
    key_prefix="sample_cmp",
    include_enable_toggle=True,
    default_statuses=status_default,
    enabled_default=bool(status_cfg.get("enabled_default", True)),
)
if not selected_file_labels:
    st.info("Select at least one report above to compare.")
    st.stop()

raw_sample_frames: dict[str, pd.DataFrame] = {}
raw_sample_default_names: dict[str, str] = {}
raw_sample_paths: dict[str, Path] = {}
used_default_names: set[str] = set()
invalid_excluded_for_analysis = 0
rejected_excluded_for_analysis = 0
allowed_statuses = {str(s).strip().lower() for s in status_selected}
for lbl in selected_file_labels:
    path = file_labels[lbl]
    report_mtime_ns = int(path.stat().st_mtime_ns)
    overrides_mtime_ns = override_mtime_ns_for_report(path)
    df = load_spectra_dataframe(str(path), report_mtime_ns, overrides_mtime_ns)
    if df.empty:
        continue
    if hide_rejected and "review_decision" in df.columns:
        before_rej = len(df)
        df = df[df["review_decision"].astype(str).str.strip().str.lower() != "rejected"]
        rejected_excluded_for_analysis += max(before_rej - len(df), 0)
    if status_filter_on and "fit_status" in df.columns:
        if not allowed_statuses:
            continue
        status_col = df["fit_status"].astype(str).str.strip().str.lower()
        if "invalid" not in allowed_statuses:
            invalid_excluded_for_analysis += int((status_col == "invalid").sum())
        df = df[status_col.isin(allowed_statuses)]
    if df.empty:
        continue
    sample_id = str(path.resolve())
    sample_name = _unique_label(_clean_sample_name(path), used_default_names)
    raw_sample_frames[sample_id] = df.reset_index(drop=True)
    raw_sample_default_names[sample_id] = sample_name
    raw_sample_paths[sample_id] = path

if not raw_sample_frames:
    st.warning("No rows left after filtering. Try changing selected reports or fit_status filter.")
    st.stop()

status_summary = ", ".join(status_selected) if (status_filter_on and status_selected) else ("all (filter off)" if not status_filter_on else "none")
st.caption(
    f"Active filter: fit_status={status_summary} | Exclude rejected={hide_rejected} | "
    f"Reports={len(raw_sample_frames)} | Excluded: invalid={invalid_excluded_for_analysis}, rejected={rejected_excluded_for_analysis}"
)

default_colors_by_id = categorical_colors(raw_sample_frames.keys())
ctrl_seg, ctrl_samples, ctrl_analysis, ctrl_fig = st.columns([2.1, 1.25, 1.35, 1.25], vertical_alignment="center")

display_name_by_id: dict[str, str] = {}
display_color_by_id: dict[str, str] = {}
duplicate_name_resolved = False
with ctrl_samples.popover("Manage samples", width="stretch"):
    st.caption("Display name and colour for each report.")
    for sample_id in raw_sample_frames:
        default_name = raw_sample_default_names[sample_id]
        path = raw_sample_paths[sample_id]
        name_key = f"sample_cmp_name::{path.as_posix()}"
        color_key = f"sample_cmp_color::{path.as_posix()}"
        if name_key not in st.session_state:
            st.session_state[name_key] = default_name
        if color_key not in st.session_state:
            st.session_state[color_key] = default_colors_by_id[sample_id]
        name_col, color_col = st.columns([5, 1], vertical_alignment="bottom")
        display_name = name_col.text_input(default_name, key=name_key)
        display_color = color_col.color_picker(
            f"Color: {default_name}",
            key=color_key,
            label_visibility="collapsed",
        )
        display_name_by_id[sample_id] = str(display_name).strip() or default_name
        display_color_by_id[sample_id] = str(display_color)

sample_frames: dict[str, pd.DataFrame] = {}
color_map: dict[str, str] = {}
used_display_names: set[str] = set()
for sample_id, frame in raw_sample_frames.items():
    requested_name = display_name_by_id[sample_id]
    final_name = _unique_label(requested_name, used_display_names)
    if final_name != requested_name:
        duplicate_name_resolved = True
    sample_frames[final_name] = frame
    color_map[final_name] = display_color_by_id[sample_id]

if duplicate_name_resolved:
    ctrl_samples.caption("Duplicate names auto-suffixed.")

pl_flags = [_is_pl_frame(frame) for frame in sample_frames.values()]
if any(pl_flags) and not all(pl_flags):
    st.warning("Select either PL reports or Raman reports, not both, for Sample Comparison.")
    st.stop()
is_pl_mode = all(pl_flags)

with ctrl_analysis.popover("Analysis settings", width="stretch"):
    sample_opts = list(sample_frames.keys())
    ref_key = "sample_cmp_ref_sample"
    if ref_key not in st.session_state or st.session_state[ref_key] not in sample_opts:
        st.session_state[ref_key] = sample_opts[0]
    ref_sample = st.selectbox(
        "Reference sample",
        options=sample_opts,
        key=ref_key,
        disabled=is_pl_mode,
        help="Its mean E2g / A1g positions are the zero point for strain and doping.",
    )
    m1, m2 = st.columns(2)
    center_options = ["median", "mean"]
    center_default = str(sample_cfg.get("center_metric_default", "median")).strip().lower()
    c_key = "sample_cmp_center_metric"
    if c_key not in st.session_state or st.session_state[c_key] not in center_options:
        st.session_state[c_key] = center_default if center_default in center_options else "median"
    center_metric = m1.selectbox("Center metric", options=center_options, key=c_key)

    error_options = ["std", "sem", "mad", "iqr"]
    error_default = str(sample_cfg.get("error_metric_default", "std")).strip().lower()
    e_key = "sample_cmp_error_metric"
    if e_key not in st.session_state or st.session_state[e_key] not in error_options:
        st.session_state[e_key] = error_default if error_default in error_options else "std"
    error_metric = m2.selectbox("Error metric", options=error_options, key=e_key)

    st.markdown("**Strain / doping coefficients**")
    st.caption("Defaults are placeholders. Use calibrated values when available.")
    k1, k2 = st.columns(2)
    for k_name, default_val in (
        ("se", float(coefficients["s_e"])),
        ("sa", float(coefficients["s_a"])),
        ("de", float(coefficients["d_e"])),
        ("da", float(coefficients["d_a"])),
    ):
        state_k = f"sample_cmp_coeff_{k_name}"
        if state_k not in st.session_state:
            st.session_state[state_k] = default_val
    s_e = k1.number_input(
        "S_E",
        format="%.4f",
        key="sample_cmp_coeff_se",
        disabled=is_pl_mode,
        help="E2g shift sensitivity to strain (unit: cm^-1 per % strain).",
    )
    s_a = k2.number_input(
        "S_A",
        format="%.4f",
        key="sample_cmp_coeff_sa",
        disabled=is_pl_mode,
        help="A1g shift sensitivity to strain (unit: cm^-1 per % strain).",
    )
    d_e = k1.number_input(
        "D_E",
        format="%.4f",
        key="sample_cmp_coeff_de",
        disabled=is_pl_mode,
        help="E2g shift sensitivity to doping (unit: cm^-1 per 1e13 cm^-2).",
    )
    d_a = k2.number_input(
        "D_A",
        format="%.4f",
        key="sample_cmp_coeff_da",
        disabled=is_pl_mode,
        help="A1g shift sensitivity to doping (unit: cm^-1 per 1e13 cm^-2).",
    )

fig_opts: dict[str, object] = {}


def _render_sample_figure_extra() -> None:
    st.divider()
    st.caption("Sample Comparison scatter & isoline options")
    if "sample_cmp_overlay_scatter" not in st.session_state:
        st.session_state["sample_cmp_overlay_scatter"] = bool(sample_cfg.get("overlay_scatter_default", True))
    if "sample_cmp_show_isolines" not in st.session_state:
        st.session_state["sample_cmp_show_isolines"] = bool(isoline_cfg.get("show_default", True))
    isoline_density_options = ["light", "normal"]
    isoline_density_default = str(isoline_cfg.get("density_default", "light")).strip().lower()
    if isoline_density_default not in isoline_density_options:
        isoline_density_default = "light"
    if (
        "sample_cmp_isoline_density" not in st.session_state
        or st.session_state["sample_cmp_isoline_density"] not in isoline_density_options
    ):
        st.session_state["sample_cmp_isoline_density"] = isoline_density_default

    overlay_val = st.checkbox("Overlay point clouds on errorbars", key="sample_cmp_overlay_scatter")
    isolines_val = st.checkbox("Show absolute isolines", key="sample_cmp_show_isolines", disabled=is_pl_mode)
    density_val = st.selectbox(
        "Isoline density",
        options=isoline_density_options,
        key="sample_cmp_isoline_density",
        disabled=is_pl_mode or (not isolines_val),
    )
    st.markdown("**Scatter Style**")
    if "sample_cmp_style_enabled" not in st.session_state:
        st.session_state["sample_cmp_style_enabled"] = True
    style_on = st.checkbox(
        "Adjust style",
        key="sample_cmp_style_enabled",
        help="Off: the common look without the adjustments below.",
    )
    style_off = not style_on
    style_defaults = {
        "sample_cmp_style_font": int(ScatterStyle.font_size),
        "sample_cmp_style_point": int(ScatterStyle.point_size),
        "sample_cmp_style_center": int(ScatterStyle.center_size),
        "sample_cmp_style_errorbar": float(ScatterStyle.errorbar_width),
        "sample_cmp_style_opacity": float(ScatterStyle.point_opacity),
        "sample_cmp_style_legend": ScatterStyle.legend_position,
        "sample_cmp_style_ticks": ScatterStyle.tick_direction,
        "sample_cmp_style_outline": bool(ScatterStyle.point_outline),
    }
    for s_key, s_val in style_defaults.items():
        if s_key not in st.session_state:
            st.session_state[s_key] = s_val
    fs1, fs2 = st.columns(2)
    style_obj = ScatterStyle(
        font_size=int(fs1.number_input("Font size", 8, 28, step=1, key="sample_cmp_style_font", disabled=style_off)),
        point_size=int(fs2.number_input("Point size", 2, 24, step=1, key="sample_cmp_style_point", disabled=style_off)),
        center_size=int(fs1.number_input("Center size", 4, 30, step=1, key="sample_cmp_style_center", disabled=style_off)),
        errorbar_width=float(
            fs2.number_input("Error bar width", 0.5, 5.0, step=0.1, key="sample_cmp_style_errorbar", disabled=style_off)
        ),
        point_opacity=float(
            fs1.slider("Point opacity", 0.1, 1.0, step=0.05, key="sample_cmp_style_opacity", disabled=style_off)
        ),
        legend_position=str(st.selectbox("Legend", LEGEND_POSITIONS, key="sample_cmp_style_legend", disabled=style_off)),
        tick_direction=str(
            st.radio("Tick direction", TICK_DIRECTIONS, horizontal=True, key="sample_cmp_style_ticks", disabled=style_off)
        ),
        point_outline=bool(st.checkbox("White outline on points", key="sample_cmp_style_outline", disabled=style_off)),
    )
    fig_opts.update(
        {
            "overlay_scatter": bool(overlay_val),
            "show_absolute_isolines": bool(isolines_val),
            "isoline_density": str(density_val),
            "use_paper_style": bool(style_on),
            "scatter_style": style_obj,
        }
    )


figure_settings_popover(
    ["sample_scatter", "sample_square", "sample_heatmap", "sample_pl"],
    extra=_render_sample_figure_extra,
    container=ctrl_fig,
)

overlay_scatter = bool(fig_opts["overlay_scatter"])
show_absolute_isolines = bool(fig_opts["show_absolute_isolines"])
isoline_density = str(fig_opts["isoline_density"])
use_paper_style = bool(fig_opts["use_paper_style"])
scatter_style = fig_opts["scatter_style"]

with ctrl_seg:
    st.caption("PL cross-sample & temperature mode" if is_pl_mode else "Raman strain/doping & LO comparison")

if is_pl_mode:
    _render_pl_comparison(
        sample_frames,
        color_map=color_map,
        center_metric=center_metric,
        error_metric=error_metric,
        overlay_scatter=overlay_scatter,
        scatter_style=scatter_style if use_paper_style else None,
    )
    st.stop()

plot_groups = ("eps-n", "Absolute Positions", "n vs FWHM", "FWHM Pair", "LO Ratio")
plot_store = st.session_state.setdefault("sample_cmp_plot_group_store", {"group": "eps-n"})
plot_key = "sample_cmp_plot_group"
if plot_key not in st.session_state or st.session_state[plot_key] not in plot_groups:
    st.session_state[plot_key] = plot_store["group"] if plot_store.get("group") in plot_groups else "eps-n"
active_plot_group = (
    st.segmented_control(
        "Comparison plot",
        options=plot_groups,
        key=plot_key,
        label_visibility="collapsed",
    )
    or "eps-n"
)
plot_store["group"] = active_plot_group

selected_step_cfg = (
    isoline_steps_cfg.get(isoline_density, {})
    if isinstance(isoline_steps_cfg, dict)
    else {}
)
eps_step = float(
    selected_step_cfg.get("eps_step", 0.1)
)
n_step = float(
    selected_step_cfg.get("n_step", 0.1)
)

ref_e2g, ref_a1g = _extract_vectors(sample_frames[ref_sample], ["e2g_position", "a1g_position"])
if ref_e2g.size == 0:
    st.error("Reference sample has no valid E2g/A1g positions after filtering.")
    st.stop()
omega_e0 = float(np.mean(ref_e2g))
omega_a0 = float(np.mean(ref_a1g))

determinant = float(s_e * d_a - s_a * d_e)
if abs(determinant) < 1e-12:
    st.error("Coefficient determinant is near zero. Adjust S_E, S_A, D_E, D_A.")
    st.stop()

summary_rows: list[dict[str, object]] = []
for sample, frame in sample_frames.items():
    e2g, a1g = _extract_vectors(frame, ["e2g_position", "a1g_position"])
    e2g_fwhm, a1g_fwhm = _extract_vectors(frame, ["e2g_fwhm", "a1g_fwhm"])
    lo_ratio_vec, lo_ratio_source = _resolve_lo_ratio_vector(frame)
    lo_ratio_valid = int(np.isfinite(lo_ratio_vec).sum()) if lo_ratio_vec.size else 0
    summary_rows.append(
        {
            "sample": sample,
            "rows_after_filter": int(len(frame)),
            "valid_e2g_a1g": int(e2g.size),
            "valid_e2g_fwhm_a1g_fwhm": int(e2g_fwhm.size),
            "valid_lo_ratio": lo_ratio_valid,
            "lo_ratio_source": lo_ratio_source,
        }
    )

top_cols = st.columns([1.2, 1, 1, 1])
top_cols[0].metric("Samples", len(sample_frames))
top_cols[1].metric("Reference", ref_sample)
top_cols[2].metric("omega_e0", f"{omega_e0:.4f}")
top_cols[3].metric("omega_a0", f"{omega_a0:.4f}")

st.dataframe(pd.DataFrame(summary_rows), width="stretch", height=220, hide_index=True)

try:
    epsn_maps, _, _ = _collect_eps_n(
        samples=sample_frames,
        omega_e0=omega_e0,
        omega_a0=omega_a0,
        s_e=float(s_e),
        s_a=float(s_a),
        d_e=float(d_e),
        d_a=float(d_a),
    )
    n_a1g_maps, _, _ = _collect_n_vs_fwhm(
        samples=sample_frames,
        fwhm_col="a1g_fwhm",
        omega_e0=omega_e0,
        omega_a0=omega_a0,
        s_e=float(s_e),
        s_a=float(s_a),
        d_e=float(d_e),
        d_a=float(d_a),
    )
    n_e2g_maps, _, _ = _collect_n_vs_fwhm(
        samples=sample_frames,
        fwhm_col="e2g_fwhm",
        omega_e0=omega_e0,
        omega_a0=omega_a0,
        s_e=float(s_e),
        s_a=float(s_a),
        d_e=float(d_e),
        d_a=float(d_a),
    )
    lo_n_maps, _, _, lo_ratio_source_n = _collect_lo_ratio_vs_n(
        samples=sample_frames,
        omega_e0=omega_e0,
        omega_a0=omega_a0,
        s_e=float(s_e),
        s_a=float(s_a),
        d_e=float(d_e),
        d_a=float(d_a),
    )
    lo_eps_maps, _, _, lo_ratio_source_eps = _collect_lo_ratio_vs_eps(
        samples=sample_frames,
        omega_e0=omega_e0,
        omega_a0=omega_a0,
        s_e=float(s_e),
        s_a=float(s_a),
        d_e=float(d_e),
        d_a=float(d_a),
    )
    lo_a1g_fwhm_maps, _, _, lo_ratio_source_a1g = _collect_lo_ratio_vs_fwhm(
        samples=sample_frames,
        fwhm_col="a1g_fwhm",
    )
    lo_e2g_fwhm_maps, _, _, lo_ratio_source_e2g = _collect_lo_ratio_vs_fwhm(
        samples=sample_frames,
        fwhm_col="e2g_fwhm",
    )
except ValueError as exc:
    st.error(str(exc))
    st.stop()

absolute_maps, _, _ = _collect_absolute_positions(sample_frames)
fwhm_maps, _, _ = _collect_fwhm_pair(sample_frames)

if not any(
    [
        epsn_maps,
        n_a1g_maps,
        n_e2g_maps,
        absolute_maps,
        fwhm_maps,
        lo_n_maps,
        lo_eps_maps,
        lo_a1g_fwhm_maps,
        lo_e2g_fwhm_maps,
    ]
):
    st.warning("No plottable numeric data after filtering.")
    st.stop()

def _show_styled(fig: go.Figure, kind: str = "sample_scatter") -> None:
    """Render a comparison figure with Figure settings and Scatter style."""
    if use_paper_style:
        apply_scatter_style(fig, scatter_style)
    show(fig, kind, filename="sample_comparison")


if active_plot_group == "eps-n":
    if epsn_maps:
        c1, c2 = st.columns(2, gap="medium")
        with c1, st.container(border=True):
            panel_title("ε-n Scatter")
            fig = _build_scatter_figure(
                data=epsn_maps,
                colors=color_map,
                title="eps-n scatter",
                x_label="Strain eps (%)",
                y_label=DOPING_N_AXIS_LABEL,
                add_zero_lines=True,
            )
            _show_styled(fig)
        with c2, st.container(border=True):
            panel_title(f"ε-n Summary ({center_metric} +/- {error_metric})")
            fig = _build_errorbar_figure(
                data=epsn_maps,
                colors=color_map,
                title=f"eps-n errorbars ({center_metric} +/- {error_metric})",
                x_label="Strain eps (%)",
                y_label=DOPING_N_AXIS_LABEL,
                center_metric=center_metric,
                error_metric=error_metric,
                overlay_scatter=overlay_scatter,
                add_zero_lines=True,
            )
            _show_styled(fig)
    else:
        st.info("No valid eps-n data in the selected reports.")

elif active_plot_group == "n vs FWHM":
    left, right = st.columns(2, gap="medium")
    with left:
        if n_a1g_maps:
            with st.container(border=True):
                panel_title("n vs A1g FWHM Scatter")
                fig = _build_scatter_figure(
                    data=n_a1g_maps,
                    colors=color_map,
                    title="n vs A1g FWHM scatter",
                    x_label=DOPING_N_AXIS_LABEL,
                    y_label="A1g FWHM (cm^-1)",
                    add_zero_lines=True,
                )
                _show_styled(fig)

            with st.container(border=True):
                panel_title("n vs A1g FWHM Errorbars")
                fig = _build_errorbar_figure(
                    data=n_a1g_maps,
                    colors=color_map,
                    title=f"n vs A1g FWHM errorbars ({center_metric} +/- {error_metric})",
                    x_label=DOPING_N_AXIS_LABEL,
                    y_label="A1g FWHM (cm^-1)",
                    center_metric=center_metric,
                    error_metric=error_metric,
                    overlay_scatter=overlay_scatter,
                    add_zero_lines=True,
                )
                _show_styled(fig)
        else:
            st.info("No valid n vs A1g FWHM data.")
    with right:
        if n_e2g_maps:
            with st.container(border=True):
                panel_title("n vs E2g FWHM Errorbars")
                fig = _build_errorbar_figure(
                    data=n_e2g_maps,
                    colors=color_map,
                    title=f"n vs E2g FWHM errorbars ({center_metric} +/- {error_metric})",
                    x_label=DOPING_N_AXIS_LABEL,
                    y_label="E2g FWHM (cm^-1)",
                    center_metric=center_metric,
                    error_metric=error_metric,
                    overlay_scatter=overlay_scatter,
                    add_zero_lines=True,
                )
                _show_styled(fig)
        else:
            st.info("No valid n vs E2g FWHM data.")

elif active_plot_group == "Absolute Positions":
    if absolute_maps:
        with st.container(border=True):
            panel_title("E2g vs A1g Absolute Positions")
            fig = _build_errorbar_figure(
                data=absolute_maps,
                colors=color_map,
                title=f"E2g vs A1g absolute errorbars ({center_metric} +/- {error_metric})",
                x_label="E2g position (cm^-1)",
                y_label="A1g position (cm^-1)",
                center_metric=center_metric,
                error_metric=error_metric,
                overlay_scatter=overlay_scatter,
                add_zero_lines=False,
            )

            x_all = np.concatenate([vals[0] for vals in absolute_maps.values()]) if absolute_maps else np.array([])
            y_all = np.concatenate([vals[1] for vals in absolute_maps.values()]) if absolute_maps else np.array([])
            x_range = _auto_axis_range(x_all, pad_ratio=0.12, min_span=0.8)
            y_range = _auto_axis_range(y_all, pad_ratio=0.12, min_span=0.8)
            if x_range is not None:
                fig.update_xaxes(range=x_range)
            if y_range is not None:
                fig.update_yaxes(range=y_range)

            # Keep default view visually balanced, but do not lock aspect during zoom/pan.
            fig.update_layout(height=720)
            fig.update_xaxes(fixedrange=False, zeroline=False)
            fig.update_yaxes(fixedrange=False, zeroline=False)

            if show_absolute_isolines:
                _add_absolute_isolines(
                    fig=fig,
                    omega_e0=omega_e0,
                    omega_a0=omega_a0,
                    s_e=float(s_e),
                    s_a=float(s_a),
                    d_e=float(d_e),
                    d_a=float(d_a),
                    eps_step=eps_step,
                    n_step=n_step,
                    eps_range=isoline_eps_range,
                    n_range=isoline_n_range,
                )
            _show_styled(fig, "sample_square")
    else:
        st.info("No valid absolute E2g/A1g position data.")

elif active_plot_group == "FWHM Pair":
    if fwhm_maps:
        with st.container(border=True):
            panel_title("E2g FWHM vs A1g FWHM")
            fig = _build_errorbar_figure(
                data=fwhm_maps,
                colors=color_map,
                title=f"E2g FWHM vs A1g FWHM ({center_metric} +/- {error_metric})",
                x_label="E2g FWHM (cm^-1)",
                y_label="A1g FWHM (cm^-1)",
                center_metric=center_metric,
                error_metric=error_metric,
                overlay_scatter=overlay_scatter,
                add_zero_lines=False,
            )
            fwhm_x_all = np.concatenate([vals[0] for vals in fwhm_maps.values()]) if fwhm_maps else np.array([])
            fwhm_y_all = np.concatenate([vals[1] for vals in fwhm_maps.values()]) if fwhm_maps else np.array([])
            fwhm_x_range = _auto_axis_range(fwhm_x_all, pad_ratio=0.12, min_span=1.0)
            fwhm_y_range = _auto_axis_range(fwhm_y_all, pad_ratio=0.12, min_span=1.0)
            if fwhm_x_range is not None:
                fig.update_xaxes(range=fwhm_x_range)
            if fwhm_y_range is not None:
                fig.update_yaxes(range=fwhm_y_range)
            fig.update_layout(height=720)
            fig.update_xaxes(fixedrange=False)
            fig.update_yaxes(fixedrange=False)
            _show_styled(fig, "sample_square")
    else:
        st.info("No valid E2g/A1g FWHM pair data.")

else:
    source_info = {}
    source_info.update(lo_ratio_source_n)
    source_info.update(lo_ratio_source_eps)
    source_info.update(lo_ratio_source_a1g)
    source_info.update(lo_ratio_source_e2g)
    if source_info:
        source_text = ", ".join([f"{k}: {v}" for k, v in sorted(source_info.items())])
        st.caption(f"LO ratio source by sample -> {source_text}")
    else:
        st.caption("LO ratio source unavailable (missing LO/A1g area and height data).")

    c1, c2 = st.columns(2, gap="medium")
    with c1:
        if lo_n_maps:
            with st.container(border=True):
                panel_title("LO ratio vs n")
                fig = _build_errorbar_figure(
                    data=lo_n_maps,
                    colors=color_map,
                    title=f"LO ratio vs n ({center_metric} +/- {error_metric})",
                    x_label=DOPING_N_AXIS_LABEL,
                    y_label="LO ratio (LO/A1g)",
                    center_metric=center_metric,
                    error_metric=error_metric,
                    overlay_scatter=overlay_scatter,
                    add_zero_lines=True,
                )
                _show_styled(fig)
        else:
            st.info("No valid LO ratio vs n data.")

        if lo_eps_maps:
            with st.container(border=True):
                panel_title("LO ratio vs eps")
                fig = _build_errorbar_figure(
                    data=lo_eps_maps,
                    colors=color_map,
                    title=f"LO ratio vs eps ({center_metric} +/- {error_metric})",
                    x_label="Strain eps (%)",
                    y_label="LO ratio (LO/A1g)",
                    center_metric=center_metric,
                    error_metric=error_metric,
                    overlay_scatter=overlay_scatter,
                    add_zero_lines=True,
                )
                _show_styled(fig)
        else:
            st.info("No valid LO ratio vs eps data.")

    with c2:
        if lo_a1g_fwhm_maps:
            with st.container(border=True):
                panel_title("LO ratio vs A1g FWHM")
                fig = _build_errorbar_figure(
                    data=lo_a1g_fwhm_maps,
                    colors=color_map,
                    title=f"LO ratio vs A1g FWHM ({center_metric} +/- {error_metric})",
                    x_label="LO ratio (LO/A1g)",
                    y_label="A1g FWHM (cm^-1)",
                    center_metric=center_metric,
                    error_metric=error_metric,
                    overlay_scatter=overlay_scatter,
                    add_zero_lines=False,
                )
                _show_styled(fig)
        else:
            st.info("No valid LO ratio vs A1g FWHM data.")

        if lo_e2g_fwhm_maps:
            with st.container(border=True):
                panel_title("LO ratio vs E2g FWHM")
                fig = _build_errorbar_figure(
                    data=lo_e2g_fwhm_maps,
                    colors=color_map,
                    title=f"LO ratio vs E2g FWHM ({center_metric} +/- {error_metric})",
                    x_label="LO ratio (LO/A1g)",
                    y_label="E2g FWHM (cm^-1)",
                    center_metric=center_metric,
                    error_metric=error_metric,
                    overlay_scatter=overlay_scatter,
                    add_zero_lines=False,
                )
                _show_styled(fig)
        else:
            st.info("No valid LO ratio vs E2g FWHM data.")

    with st.expander("LO ratio heatmap", expanded=False):
        heatmap_samples = [s for s, frame in sample_frames.items() if {"map_x", "map_y"}.issubset(frame.columns)]
        if not heatmap_samples:
            st.info("No sample has map_x/map_y columns for heatmap rendering.")
        else:
            selected_heatmap_sample = st.selectbox("Sample for heatmap", options=heatmap_samples)
            use_log10 = st.checkbox("Use log10 scale", value=False, key="lo_ratio_heatmap_log10")
            heatmap_fig = _build_lo_ratio_heatmap(
                sample_name=selected_heatmap_sample,
                frame=sample_frames[selected_heatmap_sample],
                use_log10=use_log10,
            )
            if heatmap_fig is None:
                st.info("No valid LO ratio map values for selected sample.")
            else:
                show(heatmap_fig, "sample_heatmap", filename=f"{selected_heatmap_sample}_lo_ratio_heatmap")

