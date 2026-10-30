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

from fitting.mos2_core.core.runtime_paths import runtime_project_root  # noqa: E402
from fitting.mos2_core.review.manual_overrides import override_mtime_ns_for_report  # noqa: E402

ROOT = runtime_project_root(__file__, 2)
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from gui.components import report_loader as _report_loader  # noqa: E402
from gui.components.plot_theme import apply_plotly_theme  # noqa: E402
from gui.components.science_settings import strain_doping_settings  # noqa: E402

list_report_json_files = _report_loader.list_report_json_files
load_spectra_dataframe = _report_loader.load_spectra_dataframe
load_graph_config = getattr(_report_loader, "load_graph_config", lambda: {})

DOPING_N_AXIS_LABEL = "Doping n (10^13 cm^-2)"

apply_plotly_theme()


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


def _render_pl_comparison(sample_frames: dict[str, pd.DataFrame]) -> None:
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
        "pl_position",
        "pl_fwhm",
        "rmse",
        "r2",
    ]

    rows: list[pd.DataFrame] = []
    for sample_name, frame in sample_frames.items():
        work = frame.copy()
        work["sample"] = sample_name
        work["temperature_k"] = work.apply(_temperature_from_row, axis=1)
        work["treatment_label"] = work.apply(lambda row: _treatment_from_row(row, sample_name), axis=1)
        rows.append(work)
    combined = pd.concat(rows, ignore_index=True)
    combined = combined[pd.to_numeric(combined["temperature_k"], errors="coerce").notna()].copy()
    combined["temperature_k"] = pd.to_numeric(combined["temperature_k"], errors="coerce")

    available_metrics = [
        col
        for col in metric_candidates
        if col in combined.columns and pd.to_numeric(combined[col], errors="coerce").notna().any()
    ]
    if not available_metrics:
        st.warning("No PL comparison metrics found in the selected reports.")
        return

    st.subheader("PL Temperature / Treatment Comparison")
    selected_metric = st.selectbox("PL metric", options=available_metrics, index=0)
    plot_df = combined[["sample", "treatment_label", "temperature_k", selected_metric]].copy()
    plot_df[selected_metric] = pd.to_numeric(plot_df[selected_metric], errors="coerce")
    plot_df = plot_df.dropna(subset=["temperature_k", selected_metric]).sort_values(["treatment_label", "temperature_k"])

    fig = px.line(
        plot_df,
        x="temperature_k",
        y=selected_metric,
        color="treatment_label",
        markers=True,
        hover_data=["sample"],
    )
    fig.update_layout(xaxis_title="Temperature (K)", yaxis_title=selected_metric)
    st.plotly_chart(fig, width="stretch")

    table_cols = ["sample", "treatment_label", "temperature_k", *available_metrics]
    st.dataframe(
        combined[table_cols].sort_values(["temperature_k", "treatment_label"]),
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
    labels = set(combined["treatment_label"].astype(str))
    if {"Pristine", "Treatment"}.issubset(labels) and pair_metrics:
        paired_rows: list[dict[str, float | str]] = []
        for temp, group in combined.groupby("temperature_k"):
            pristine = group[group["treatment_label"].astype(str) == "Pristine"]
            treatment = group[group["treatment_label"].astype(str) == "Treatment"]
            if pristine.empty or treatment.empty:
                continue
            out: dict[str, float | str] = {"temperature_k": float(temp)}
            p_row = pristine.iloc[0]
            t_row = treatment.iloc[0]
            for metric in pair_metrics:
                p_val = pd.to_numeric(pd.Series([p_row.get(metric)]), errors="coerce").iloc[0]
                t_val = pd.to_numeric(pd.Series([t_row.get(metric)]), errors="coerce").iloc[0]
                if pd.notna(p_val) and pd.notna(t_val):
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
    det_k = s_e * d_a - s_a * d_e
    if abs(det_k) < 1e-12:
        raise ValueError("Invalid coefficient set: determinant is near zero.")
    d_e2g = e2g - omega_e0
    d_a1g = a1g - omega_a0
    eps = (d_a * d_e2g - d_e * d_a1g) / det_k
    n = (-s_a * d_e2g + s_e * d_a1g) / det_k
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
        color_continuous_scale="Viridis",
        labels={"x": "map_x", "y": "map_y", "color": color_label},
        title=f"LO ratio heatmap: {sample_name}",
    )
    fig.update_layout(template="plotly_white")
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
                marker={"size": 6, "opacity": 0.65, "color": colors[sample]},
            )
        )
    if add_zero_lines:
        fig.add_hline(y=0.0, line_width=1, line_dash="dot", line_color="gray")
        fig.add_vline(x=0.0, line_width=1, line_dash="dot", line_color="gray")
    fig.update_layout(
        template="plotly_white",
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
                    marker={"size": 5, "opacity": 0.35, "color": colors[sample]},
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
                marker={"size": 11, "color": colors[sample], "line": {"width": 1.5, "color": "black"}},
                error_x={
                    "type": "data",
                    "array": [ex if np.isfinite(ex) else 0.0],
                    "visible": bool(np.isfinite(ex)),
                    "thickness": 1.2,
                    "width": 3,
                    "color": "black",
                },
                error_y={
                    "type": "data",
                    "array": [ey if np.isfinite(ey) else 0.0],
                    "visible": bool(np.isfinite(ey)),
                    "thickness": 1.2,
                    "width": 3,
                    "color": "black",
                },
                hovertemplate=(
                    f"{sample}<br>center_x=%{{x:.4f}}<br>center_y=%{{y:.4f}}"
                    f"<br>{error_metric}_x={ex:.4f}<br>{error_metric}_y={ey:.4f}<extra></extra>"
                ),
            )
        )
    if add_zero_lines:
        fig.add_hline(y=0.0, line_width=1, line_dash="dot", line_color="gray")
        fig.add_vline(x=0.0, line_width=1, line_dash="dot", line_color="gray")
    fig.update_layout(
        template="plotly_white",
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
                showlegend=False,
                hoverinfo="skip",
                line={"dash": "dash", "width": 1, "color": "rgba(120,120,120,0.35)"},
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
                showlegend=False,
                hoverinfo="skip",
                line={"dash": "dot", "width": 1, "color": "rgba(120,120,120,0.35)"},
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


st.title("Sample Comparison")
st.caption("Cross-sample comparison plots derived from fit report outputs.")

graph_cfg = load_graph_config()
sample_cfg = graph_cfg.get("sample_comparison", {}) if isinstance(graph_cfg, dict) else {}
status_cfg = sample_cfg.get("status_filter", {}) if isinstance(sample_cfg, dict) else {}
isoline_cfg = sample_cfg.get("absolute_isolines", {}) if isinstance(sample_cfg, dict) else {}
isoline_steps_cfg = isoline_cfg.get("steps", {}) if isinstance(isoline_cfg, dict) else {}

# Strain/doping coefficients and isoline spans: strain (%), carrier density (1e13 cm^-2).
strain_doping = strain_doping_settings(graph_cfg)
coefficients = strain_doping["coefficients"]
isoline_eps_range = strain_doping["eps_range"]
isoline_n_range = strain_doping["n_range"]

report_files = list_report_json_files()
if not report_files:
    st.warning(
        "No report JSON files found in data/results/{raman,pl}/reports."
    )
    st.stop()

file_labels: dict[str, Path] = {}
for report in report_files:
    stamp = report.stat().st_mtime
    label = f"{report.name}  ({pd.to_datetime(stamp, unit='s').strftime('%Y-%m-%d %H:%M:%S')})"
    file_labels[label] = report

default_count = min(max(int(sample_cfg.get("default_report_count", 4)), 1), len(file_labels))
st.sidebar.subheader("1) Report Source")
status_options = ["valid", "attention", "invalid"]
status_default_raw = status_cfg.get("allowed_default", ["valid", "attention"])
if isinstance(status_default_raw, list):
    status_default = [str(v).strip().lower() for v in status_default_raw if str(v).strip().lower() in status_options]
else:
    status_default = ["valid", "attention"]
if not status_default:
    status_default = ["valid", "attention"]
with st.sidebar.expander("2) Filters", expanded=True):
    selected_file_labels = st.multiselect(
        "Reports to compare",
        options=list(file_labels.keys()),
        default=list(file_labels.keys())[:default_count],
    )
    status_filter_on = st.checkbox(
        "Filter by fit_status",
        value=bool(status_cfg.get("enabled_default", True)),
    )
    status_selected = st.multiselect(
        "Allowed fit_status values",
        options=status_options,
        default=status_default,
        disabled=not status_filter_on,
    )
if not selected_file_labels:
    st.info("Select at least one report in the sidebar.")
    st.stop()

raw_sample_frames: dict[str, pd.DataFrame] = {}
raw_sample_default_names: dict[str, str] = {}
raw_sample_paths: dict[str, Path] = {}
used_default_names: set[str] = set()
invalid_excluded_for_analysis = 0
for lbl in selected_file_labels:
    path = file_labels[lbl]
    report_mtime_ns = int(path.stat().st_mtime_ns)
    overrides_mtime_ns = override_mtime_ns_for_report(path)
    df = load_spectra_dataframe(str(path), report_mtime_ns, overrides_mtime_ns)
    if df.empty:
        continue
    if status_filter_on and status_selected and "fit_status" in df.columns:
        df = df[df["fit_status"].astype(str).isin(status_selected)]
    if "fit_status" in df.columns:
        before_count = len(df)
        df = df[df["fit_status"].astype(str).str.strip().str.lower() != "invalid"]
        invalid_excluded_for_analysis += max(before_count - len(df), 0)
    sample_id = str(path.resolve())
    sample_name = _unique_label(_clean_sample_name(path), used_default_names)
    raw_sample_frames[sample_id] = df.reset_index(drop=True)
    raw_sample_default_names[sample_id] = sample_name
    raw_sample_paths[sample_id] = path

if not raw_sample_frames:
    st.warning("No rows left after filtering. Try changing selected reports or fit_status filter.")
    st.stop()
if invalid_excluded_for_analysis > 0:
    st.caption(f"Excluded invalid rows from analysis: {invalid_excluded_for_analysis}")

palette = px.colors.qualitative.Dark24 + px.colors.qualitative.Plotly
default_colors_by_id = {
    sample_id: palette[i % len(palette)]
    for i, sample_id in enumerate(raw_sample_frames.keys())
}

display_name_by_id: dict[str, str] = {}
display_color_by_id: dict[str, str] = {}
with st.sidebar.expander("3) Basic Display", expanded=True):
    for sample_id in raw_sample_frames:
        default_name = raw_sample_default_names[sample_id]
        path = raw_sample_paths[sample_id]
        display_name = st.text_input(
            f"Name: {default_name}",
            value=default_name,
            key=f"sample_cmp_name::{path.as_posix()}",
        )
        display_color = st.color_picker(
            f"Color: {default_name}",
            value=default_colors_by_id[sample_id],
            key=f"sample_cmp_color::{path.as_posix()}",
        )
        display_name_by_id[sample_id] = display_name.strip() or default_name
        display_color_by_id[sample_id] = display_color

sample_frames: dict[str, pd.DataFrame] = {}
color_map: dict[str, str] = {}
used_display_names: set[str] = set()
duplicate_name_resolved = False
for sample_id, frame in raw_sample_frames.items():
    requested_name = display_name_by_id[sample_id]
    final_name = _unique_label(requested_name, used_display_names)
    if final_name != requested_name:
        duplicate_name_resolved = True
    sample_frames[final_name] = frame
    color_map[final_name] = display_color_by_id[sample_id]

if duplicate_name_resolved:
    st.sidebar.caption("Duplicate display names were auto-suffixed (e.g., '(2)').")

pl_flags = [_is_pl_frame(frame) for frame in sample_frames.values()]
if any(pl_flags):
    if not all(pl_flags):
        st.warning("Select either PL reports or Raman reports, not both, for Sample Comparison.")
        st.stop()
    _render_pl_comparison(sample_frames)
    st.stop()

with st.sidebar.expander("4) Advanced Model Params", expanded=False):
    st.caption("Defaults are placeholders. Use calibrated values when available.")
    s_e = st.number_input(
        "S_E",
        value=coefficients["s_e"],
        format="%.4f",
        help="E2g shift sensitivity to strain (unit: cm^-1 per % strain).",
    )
    s_a = st.number_input(
        "S_A",
        value=coefficients["s_a"],
        format="%.4f",
        help="A1g shift sensitivity to strain (unit: cm^-1 per % strain).",
    )
    d_e = st.number_input(
        "D_E",
        value=coefficients["d_e"],
        format="%.4f",
        help="E2g shift sensitivity to doping (unit: cm^-1 per 1e13 cm^-2).",
    )
    d_a = st.number_input(
        "D_A",
        value=coefficients["d_a"],
        format="%.4f",
        help="A1g shift sensitivity to doping (unit: cm^-1 per 1e13 cm^-2).",
    )

    center_options = ["median", "mean"]
    center_default = str(sample_cfg.get("center_metric_default", "median")).strip().lower()
    center_index = center_options.index(center_default) if center_default in center_options else 0
    center_metric = st.selectbox("Center metric", options=center_options, index=center_index)

    error_options = ["std", "sem", "mad", "iqr"]
    error_default = str(sample_cfg.get("error_metric_default", "std")).strip().lower()
    error_index = error_options.index(error_default) if error_default in error_options else 0
    error_metric = st.selectbox("Error metric", options=error_options, index=error_index)

    overlay_scatter = st.checkbox(
        "Overlay point clouds on errorbars",
        value=bool(sample_cfg.get("overlay_scatter_default", True)),
    )
    show_absolute_isolines = st.checkbox(
        "Show absolute isolines",
        value=bool(isoline_cfg.get("show_default", True)),
    )

    isoline_density_options = ["light", "normal"]
    isoline_density_default = str(isoline_cfg.get("density_default", "light")).strip().lower()
    if isoline_density_default not in isoline_density_options:
        isoline_density_default = "light"
    isoline_density = st.selectbox(
        "Isoline density",
        options=isoline_density_options,
        index=isoline_density_options.index(isoline_density_default),
    )
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

ref_sample = st.sidebar.selectbox("Reference sample", options=list(sample_frames.keys()), index=0)
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

tab_epsn, tab_absolute, tab_nfwhm, tab_fwhm, tab_lo = st.tabs(
    [
        "eps-n",
        "Absolute Positions",
        "n vs FWHM",
        "FWHM Pair",
        "LO Ratio",
    ]
)

with tab_epsn:
    if epsn_maps:
        c1, c2 = st.columns(2)
        with c1:
            fig = _build_scatter_figure(
                data=epsn_maps,
                colors=color_map,
                title="eps-n scatter",
                x_label="Strain eps (%)",
                y_label=DOPING_N_AXIS_LABEL,
                add_zero_lines=True,
            )
            st.plotly_chart(fig, width="stretch")
        with c2:
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
            st.plotly_chart(fig, width="stretch")
    else:
        st.info("No valid eps-n data in the selected reports.")

with tab_nfwhm:
    left, right = st.columns(2)
    with left:
        if n_a1g_maps:
            fig = _build_scatter_figure(
                data=n_a1g_maps,
                colors=color_map,
                title="n vs A1g FWHM scatter",
                x_label=DOPING_N_AXIS_LABEL,
                y_label="A1g FWHM (cm^-1)",
                add_zero_lines=True,
            )
            st.plotly_chart(fig, width="stretch")

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
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No valid n vs A1g FWHM data.")
    with right:
        if n_e2g_maps:
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
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No valid n vs E2g FWHM data.")

with tab_absolute:
    if absolute_maps:
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
        fig.update_xaxes(
            fixedrange=False,
            zeroline=False,
            showline=False,
            showgrid=False,
        )
        fig.update_yaxes(
            fixedrange=False,
            zeroline=False,
            showline=False,
            showgrid=False,
        )

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
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("No valid absolute E2g/A1g position data.")

with tab_fwhm:
    if fwhm_maps:
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
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("No valid E2g/A1g FWHM pair data.")

with tab_lo:
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

    c1, c2 = st.columns(2)
    with c1:
        if lo_n_maps:
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
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No valid LO ratio vs n data.")

        if lo_eps_maps:
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
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No valid LO ratio vs eps data.")

    with c2:
        if lo_a1g_fwhm_maps:
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
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No valid LO ratio vs A1g FWHM data.")

        if lo_e2g_fwhm_maps:
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
            st.plotly_chart(fig, width="stretch")
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
                st.plotly_chart(heatmap_fig, width="stretch")

