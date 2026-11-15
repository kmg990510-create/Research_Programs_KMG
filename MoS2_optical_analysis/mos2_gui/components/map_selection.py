"""What the Map Viewer shows for the points selected on the map: numbers, review decision, spectrum."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import streamlit as st

from .map_editing import REVIEW_DECISIONS, apply_decision
from .map_figure import finite_values
from .report_loader import load_report_payload, load_spectra_dataframe
from .spectrum_view import default_view_range, to_plot_axis, view_window
from .spectrum_viewer import load_raw_xy, render_spectrum_overlay, resolve_source_file


def _raw_xy(row: Mapping[str, Any], project_root: Path) -> tuple[list[float], list[float]]:
    """Measured spectrum of a row: embedded in the report, else read from its source file."""
    x_raw, y_raw = row.get("raw_x"), row.get("raw_y")
    if isinstance(x_raw, list) and isinstance(y_raw, list) and len(x_raw) == len(y_raw) and x_raw:
        return [float(v) for v in x_raw], [float(v) for v in y_raw]
    source = resolve_source_file(row.get("source_file"), project_root)
    return load_raw_xy(str(source)) if source is not None else ([], [])


def _spectrum(row: Mapping[str, Any], modality: str, graph_cfg: Mapping[str, Any], project_root: Path) -> None:
    x_raw, y_raw = _raw_xy(row, project_root)
    if not (x_raw and y_raw):
        st.caption("Raw spectrum is not embedded in this report row and source file was not found.")
        return
    row_modality = str(row.get("modality", modality)).strip().lower() or modality
    window = view_window(graph_cfg)
    x_plot, y_plot = to_plot_axis(x_raw, y_raw, row, row_modality, window)
    low, high = default_view_range(x_plot, row, row_modality, window)
    render_spectrum_overlay(
        spectrum_id=str(row["spectrum_id"]), row=dict(row), x_raw=x_plot, y_raw=y_plot, x_view_min=low, x_view_max=high
    )


def selection_panel(
    plot_df: pd.DataFrame,
    selected_ids: list[str],
    param: str,
    report_path: Path,
    modality: str,
    graph_cfg: Mapping[str, Any],
    project_root: Path,
    key: str,
    selected_state_key: str,
) -> None:
    """Statistics of the selected points, a review decision for all of them, and the spectrum of a single one."""
    picked = plot_df[plot_df["spectrum_id"].isin(selected_ids)]
    if picked.empty:
        st.info("No points selected. Drag a box on the map, or switch Mouse mode to Click.")
        return
    values = finite_values(picked, param)
    n1, n2, n3 = st.columns(3)
    n1.metric("Selected", len(picked))
    n2.metric(f"Mean {param}", f"{values.mean():.4f}" if not values.empty else "-")
    n3.metric("Std", f"{values.std(ddof=0):.4f}" if not values.empty else "-")

    d1, d2 = st.columns([1, 2])
    decision = d1.selectbox("Set review decision", REVIEW_DECISIONS, key=f"{key}_decision")
    note = d2.text_input("Note", key=f"{key}_note")
    b1, b2 = st.columns(2)
    if b1.button(f"Apply to {len(picked)} point(s)", type="primary", key=f"{key}_apply", width="stretch"):
        count = apply_decision(report_path, plot_df, selected_ids, decision, note)
        load_report_payload.clear()
        load_spectra_dataframe.clear()
        st.toast(f"Recorded '{decision}' for {count} point(s) in manual overrides.")
        st.rerun()
    if b2.button("Clear selection", key=f"{key}_clear", width="stretch"):
        st.session_state[selected_state_key] = []
        st.rerun()

    columns = [c for c in ["spectrum_id", "map_x", "map_y", param, "fit_status", "review_decision"] if c in picked.columns]
    st.dataframe(picked[columns], width="stretch", height=180, hide_index=True)
    if len(picked) == 1:
        _spectrum(picked.iloc[0].to_dict(), modality, graph_cfg, project_root)
