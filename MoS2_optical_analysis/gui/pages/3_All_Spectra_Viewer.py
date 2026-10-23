"""Page for browsing all spectra with raw/fitted overlays."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
import tempfile
from typing import Any

import pandas as pd
import streamlit as st

from fitting.mos2_core.core.runtime_paths import runtime_project_root  # noqa: E402

ROOT = runtime_project_root(__file__, 2)
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from fitting.mos2_core.review.refit_api import (  # noqa: E402
    ManualRefitRequest,
    SingleSpectrumRefitAPI,
)
from fitting.mos2_core.review.manual_overrides import (  # noqa: E402
    upsert_manual_override,
)
from gui.components import report_loader as _report_loader  # noqa: E402
from gui.components.manual_refit_contract import (  # noqa: E402
    build_editor_request,
    validate_editor_response,
)
from gui.components.spectrum_viewer import (  # noqa: E402
    load_raw_xy,
    render_fit_summary,
    render_spectrum_overlay,
    resolve_source_file,
)

choose_report_sidebar = _report_loader.choose_report_sidebar
load_graph_config = getattr(_report_loader, "load_graph_config", lambda: {})
sidebar_filters_header = getattr(_report_loader, "sidebar_filters_header", lambda: None)

_POINT_TOKEN_RE = re.compile(r"Y(?P<y>\d+)-X(?P<x>\d+)", re.IGNORECASE)
PL_DEFAULT_VIEW_MIN_EV = 1.4


def _sanitize_filename(value: str) -> str:
    text = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(value))
    return text[:120] if text else "spectrum"


def _resolve_modality(payload: dict[str, Any], row: dict[str, Any], report_path: Path) -> str:
    row_modality = str(row.get("modality", "")).strip().lower()
    if row_modality in {"raman", "pl"}:
        return row_modality
    payload_modality = str(payload.get("modality", "")).strip().lower()
    if payload_modality in {"raman", "pl"}:
        return payload_modality
    path_tokens = {part.lower() for part in report_path.parts}
    if "pl" in path_tokens:
        return "pl"
    return "raman"


def _sync_index_from_slider() -> None:
    index = int(st.session_state["all_spectra_index_slider"])
    st.session_state["all_spectra_index_value"] = index
    st.session_state["all_spectra_index_number"] = index


def _sync_index_from_number(max_index: int) -> None:
    index = int(st.session_state["all_spectra_index_number"])
    index = max(0, min(index, max_index))
    st.session_state["all_spectra_index_value"] = index
    st.session_state["all_spectra_index_slider"] = index
    st.session_state["all_spectra_index_number"] = index


def _set_linear_index(index: int) -> None:
    st.session_state["all_spectra_index_value"] = index
    st.session_state["all_spectra_index_slider"] = index
    st.session_state["all_spectra_index_number"] = index


def _derive_navigation_axes(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    y_values = (
        pd.to_numeric(frame["map_y"], errors="coerce")
        if "map_y" in frame.columns
        else pd.Series(index=frame.index, dtype="float64")
    )
    x_values = (
        pd.to_numeric(frame["map_x"], errors="coerce")
        if "map_x" in frame.columns
        else pd.Series(index=frame.index, dtype="float64")
    )

    if "spectrum_id" in frame.columns:
        parsed_from_id = frame["spectrum_id"].astype(str).str.extract(_POINT_TOKEN_RE)
        y_values = y_values.fillna(pd.to_numeric(parsed_from_id["y"], errors="coerce"))
        x_values = x_values.fillna(pd.to_numeric(parsed_from_id["x"], errors="coerce"))

    if "source_file" in frame.columns:
        parsed_from_source = frame["source_file"].astype(str).str.extract(_POINT_TOKEN_RE)
        y_values = y_values.fillna(pd.to_numeric(parsed_from_source["y"], errors="coerce"))
        x_values = x_values.fillna(pd.to_numeric(parsed_from_source["x"], errors="coerce"))

    return y_values.round().astype("Int64"), x_values.round().astype("Int64")


def _build_display_row_for_candidate(row: dict, candidate: dict) -> dict:
    """Return a clean view row with only the selected candidate fit keys."""
    display = dict(row)

    fit_scalar_keys = {
        "selected_model",
        "fitted_y",
        "peak_position",
        "peak_amplitude",
        "delta_e2g_a1g",
        "line_profile",
        "bg_slope",
        "bg_intercept",
        "aic",
        "bic",
        "rmse",
        "r2",
        "nfev",
        "n_params",
        "aic_fit",
        "bic_fit",
        "rmse_fit",
        "r2_fit",
        "comparison_n",
    }
    peak_prefixes = (
        "pl_",
        "i1_",
        "i2_",
        "a_minus_",
        "a0_",
        "b_",
        "lo_",
        "e2g_",
        "a1g_",
        "zo_",
        "la_",
    )

    for key in list(display.keys()):
        if key in fit_scalar_keys or key.startswith(peak_prefixes):
            display.pop(key, None)

    display["selected_model"] = candidate.get("model_name")
    display["fitted_y"] = candidate.get("fitted_y")

    params = candidate.get("params")
    if isinstance(params, dict):
        display.update(params)

    metrics = candidate.get("metrics")
    if isinstance(metrics, dict):
        display.update(metrics)

    return display


def _build_after_row(before_row: dict[str, Any], refit_payload: dict[str, Any]) -> dict[str, Any]:
    after = dict(before_row)
    params = refit_payload.get("params", {})
    metrics = refit_payload.get("metrics", {})
    if isinstance(params, dict):
        after.update(params)
    if isinstance(metrics, dict):
        after.update(metrics)
    after["selected_model"] = refit_payload.get("selected_model", after.get("selected_model"))
    fitted_y = refit_payload.get("fitted_y")
    if isinstance(fitted_y, list):
        after["fitted_y"] = fitted_y
    return after


def _launch_desktop_editor(request_path: Path, output_path: Path) -> subprocess.CompletedProcess[str]:
    suffix = ".exe" if sys.platform.startswith("win") else ""
    desktop_exe = None
    if getattr(sys, "frozen", False):
        candidate = Path(sys.executable).resolve().with_name(f"mos2-desktop-editor{suffix}")
        if candidate.exists():
            desktop_exe = candidate

    if desktop_exe is not None:
        cmd = [
            str(desktop_exe),
            "--request",
            str(request_path),
            "--output",
            str(output_path),
        ]
    else:
        cmd = [
            sys.executable,
            "-m",
            "gui.desktop_editor.app",
            "--request",
            str(request_path),
            "--output",
            str(output_path),
        ]
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _manual_cache_key(report_path: Path, spectrum_id: str) -> str:
    return f"{report_path.resolve()}::{spectrum_id}"


st.title("All Spectra Viewer")
st.caption("Inspect any spectrum with raw data and fitted curve overlay.")

report_path, payload, df = choose_report_sidebar("all_spectra")
if report_path is None or payload is None:
    st.stop()
if df.empty:
    st.warning("This report has no spectra rows.")
    st.stop()

graph_cfg = load_graph_config()
all_spectra_cfg = graph_cfg.get("all_spectra_viewer", {}) if isinstance(graph_cfg, dict) else {}
x_window_cfg = all_spectra_cfg.get("x_window", {}) if isinstance(all_spectra_cfg, dict) else {}
overlay_style_cfg = all_spectra_cfg.get("style", {}) if isinstance(all_spectra_cfg, dict) else {}
fit_curve_cfg = all_spectra_cfg.get("fit_curve", {}) if isinstance(all_spectra_cfg, dict) else {}
fallback_x_min = float(x_window_cfg.get("fallback_min", 340.0))
fallback_x_max = float(x_window_cfg.get("fallback_max", 430.0))
peak_padding = float(x_window_cfg.get("peak_padding", 18.0))

work_df = df.copy()
sidebar_filters_header()
if "map_id" in work_df.columns:
    map_options = ["ALL"] + sorted(work_df["map_id"].dropna().astype(str).unique().tolist())
    selected_map = st.sidebar.selectbox("Map filter", map_options, key="all_spectra_map_filter")
    if selected_map != "ALL":
        work_df = work_df[work_df["map_id"].astype(str) == selected_map]

if "selected_model" in work_df.columns:
    model_options = ["ALL"] + sorted(work_df["selected_model"].dropna().astype(str).unique().tolist())
    selected_model = st.sidebar.selectbox("Model filter", model_options, key="all_spectra_model_filter")
    if selected_model != "ALL":
        work_df = work_df[work_df["selected_model"].astype(str) == selected_model]

search_text = st.sidebar.text_input("Spectrum ID contains", value="", key="all_spectra_search")
if search_text.strip():
    work_df = work_df[work_df["spectrum_id"].astype(str).str.contains(search_text.strip(), case=False, regex=False)]

if work_df.empty:
    st.warning("No spectra left after filters.")
    st.stop()

work_df = work_df.reset_index(drop=True)
nav_y, nav_x = _derive_navigation_axes(work_df)
work_df["_nav_y"] = nav_y
work_df["_nav_x"] = nav_x
max_index = len(work_df) - 1
if "all_spectra_index_value" not in st.session_state:
    st.session_state["all_spectra_index_value"] = 0
st.session_state["all_spectra_index_value"] = max(0, min(int(st.session_state["all_spectra_index_value"]), max_index))
if "all_spectra_index_slider" not in st.session_state:
    st.session_state["all_spectra_index_slider"] = st.session_state["all_spectra_index_value"]
else:
    st.session_state["all_spectra_index_slider"] = max(
        0,
        min(int(st.session_state["all_spectra_index_slider"]), max_index),
    )
if "all_spectra_index_number" not in st.session_state:
    st.session_state["all_spectra_index_number"] = st.session_state["all_spectra_index_value"]
else:
    st.session_state["all_spectra_index_number"] = max(
        0,
        min(int(st.session_state["all_spectra_index_number"]), max_index),
    )

grid_mask = work_df["_nav_y"].notna() & work_df["_nav_x"].notna()
has_grid_navigation = bool(grid_mask.any())
st.sidebar.subheader("3) Spectrum Navigation")

if max_index == 0:
    _set_linear_index(0)
    if has_grid_navigation:
        only_row = work_df.loc[0]
        if pd.notna(only_row.get("_nav_y")):
            st.session_state["all_spectra_nav_y"] = int(only_row["_nav_y"])
        if pd.notna(only_row.get("_nav_x")):
            st.session_state["all_spectra_nav_x"] = int(only_row["_nav_x"])
    st.sidebar.caption("Only one spectrum matches current filters.")
    index = 0
elif has_grid_navigation:
    nav_df = work_df.loc[grid_mask, ["_nav_y", "_nav_x"]].copy()
    nav_df["_nav_y"] = nav_df["_nav_y"].astype(int)
    nav_df["_nav_x"] = nav_df["_nav_x"].astype(int)

    y_options = sorted(nav_df["_nav_y"].unique().tolist())
    current_index = int(st.session_state["all_spectra_index_value"])
    current_row = work_df.iloc[current_index]
    current_y = int(current_row["_nav_y"]) if pd.notna(current_row["_nav_y"]) else y_options[0]
    current_x = int(current_row["_nav_x"]) if pd.notna(current_row["_nav_x"]) else None

    selected_y_state = st.session_state.get("all_spectra_nav_y")
    if selected_y_state is None or int(selected_y_state) not in y_options:
        st.session_state["all_spectra_nav_y"] = current_y
    selected_y = int(
        st.sidebar.select_slider(
            "Row index (Y)",
            options=y_options,
            value=int(st.session_state["all_spectra_nav_y"]),
            key="all_spectra_nav_y",
        )
    )

    x_options = sorted(nav_df.loc[nav_df["_nav_y"] == selected_y, "_nav_x"].unique().tolist())
    if not x_options:
        x_options = sorted(nav_df["_nav_x"].unique().tolist())

    selected_x_state = st.session_state.get("all_spectra_nav_x")
    if selected_x_state is not None and int(selected_x_state) in x_options:
        default_x = int(selected_x_state)
    elif current_x is not None and current_x in x_options:
        default_x = current_x
    else:
        default_x = x_options[0]
    st.session_state["all_spectra_nav_x"] = default_x

    selected_x = int(
        st.sidebar.select_slider(
            "Spectrum index (X)",
            options=x_options,
            value=int(st.session_state["all_spectra_nav_x"]),
            key="all_spectra_nav_x",
        )
    )
    st.sidebar.caption("Coordinate navigation keeps X/Y control in one place.")

    match_mask = ((work_df["_nav_y"] == selected_y) & (work_df["_nav_x"] == selected_x)).fillna(False)
    matched_indexes = work_df.index[match_mask].tolist()
    if matched_indexes:
        index = int(matched_indexes[0])
    else:
        same_y_mask = (work_df["_nav_y"] == selected_y).fillna(False)
        same_y_indexes = work_df.index[same_y_mask].tolist()
        index = int(same_y_indexes[0]) if same_y_indexes else int(st.session_state["all_spectra_index_value"])

    _set_linear_index(index)
else:
    _ = st.sidebar.slider(
        "Spectrum index",
        0,
        max_index,
        int(st.session_state["all_spectra_index_slider"]),
        key="all_spectra_index_slider",
        on_change=_sync_index_from_slider,
    )
    _ = st.sidebar.number_input(
        "Spectrum index (number)",
        min_value=0,
        max_value=max_index,
        value=int(st.session_state["all_spectra_index_number"]),
        step=1,
        key="all_spectra_index_number",
        on_change=_sync_index_from_number,
        args=(max_index,),
    )
    index = int(st.session_state["all_spectra_index_value"])
row = work_df.iloc[index].to_dict()
spectrum_id = str(row.get("spectrum_id", f"row_{index}"))

top_cols = st.columns([2, 1, 1])
top_cols[0].subheader(spectrum_id)
top_cols[1].metric("Filtered Rows", len(work_df))
top_cols[2].metric("Current Index", f"{index + 1}/{len(work_df)}")
if pd.notna(work_df.at[index, "_nav_y"]) and pd.notna(work_df.at[index, "_nav_x"]):
    st.caption(f"Grid coordinate: Y{int(work_df.at[index, '_nav_y'])}-X{int(work_df.at[index, '_nav_x'])}")
st.caption(f"Row coverage: {(index + 1) / max(len(work_df), 1) * 100:.1f}%")

source_path = resolve_source_file(row.get("source_file"), ROOT)
if source_path is None:
    st.error("`source_file` is missing or invalid in this report row. Re-run pipeline with latest report format.")
    st.stop()

all_candidates = row.get("all_candidates", [])
if not isinstance(all_candidates, list):
    all_candidates = []

candidate_names = [
    c.get("model_name")
    for c in all_candidates
    if isinstance(c, dict) and isinstance(c.get("model_name"), str)
]
display_row = dict(row)
selected_candidate: dict[str, Any] | None = None
has_manual_override = bool(row.get("manual_override", False))
manual_override_action = str(row.get("manual_override_action", "")).strip()

if candidate_names:
    projected_option = "__projected_result__"
    model_options = [projected_option, *candidate_names]

    selected_model_value = str(row.get("selected_model", "")).strip()
    default_option = projected_option if has_manual_override else selected_model_value
    if default_option not in model_options:
        default_option = candidate_names[0]

    selected_model_for_view = st.selectbox(
        "Fitting model to display",
        model_options,
        index=model_options.index(default_option),
        key="all_spectra_model_choice",
        format_func=lambda value: (
            "Current projected result (manual override)"
            if value == projected_option and has_manual_override
            else ("Current projected result" if value == projected_option else value)
        ),
    )

    if selected_model_for_view != projected_option:
        selected_candidate = next(
            c for c in all_candidates if isinstance(c, dict) and c.get("model_name") == selected_model_for_view
        )
        display_row = _build_display_row_for_candidate(row=row, candidate=selected_candidate)

    if has_manual_override and manual_override_action:
        st.caption(f"Manual override active: {manual_override_action}")

if selected_candidate is not None:
    model_override_key = (
        f"apply_model_override_{_sanitize_filename(report_path.stem)}_{_sanitize_filename(spectrum_id)}"
    )
    if st.button("Apply Model Override", key=model_override_key, use_container_width=False):
        params = selected_candidate.get("params", {})
        metrics = selected_candidate.get("metrics", {})
        fitted_y = selected_candidate.get("fitted_y", [])
        override_path = upsert_manual_override(
            report_json=report_path,
            spectrum_id=spectrum_id,
            action_type="model_override",
            selected_model=str(selected_candidate.get("model_name", "")),
            params=params if isinstance(params, dict) else {},
            metrics=metrics if isinstance(metrics, dict) else {},
            fitted_y=fitted_y if isinstance(fitted_y, list) else [],
            operator_note="manual_model_override",
        )
        st.success(f"Model override saved: {override_path}")
        st.rerun()

x_raw, y_raw = load_raw_xy(str(source_path))
modality = _resolve_modality(payload=payload, row=display_row, report_path=report_path)
try:
    cal_offset = float(display_row.get("calibration_offset", 0.0) or 0.0)
except (TypeError, ValueError):
    cal_offset = 0.0
x_for_plot = [xv + cal_offset for xv in x_raw]
if modality == "pl" and str(display_row.get("x_unit", "")).strip().lower() == "ev" and x_for_plot and max(x_for_plot) > 100.0:
    converted_pairs = sorted(
        (
            (1239.8419843320026 / float(xv), float(yv))
            for xv, yv in zip(x_for_plot, y_raw)
            if float(xv) > 0.0
        ),
        key=lambda item: item[0],
    )
    x_for_plot = [xv for xv, _ in converted_pairs]
    y_raw = [yv for _, yv in converted_pairs]

pl_pos = display_row.get("pl_position")
if modality == "pl" or (modality != "raman" and pl_pos is not None and str(pl_pos).strip() != ""):
    try:
        pl_val = float(pl_pos)
        x_span = float(max(x_for_plot) - min(x_for_plot))
        pl_padding = max(0.08, min(0.25, x_span * 0.25)) if x_span <= 10.0 else max(peak_padding, 60.0)
        auto_min = max(float(min(x_for_plot)), min(PL_DEFAULT_VIEW_MIN_EV, pl_val - pl_padding))
        auto_max = min(float(max(x_for_plot)), pl_val + pl_padding)
    except (TypeError, ValueError):
        auto_min = float(min(x_for_plot))
        auto_max = float(max(x_for_plot))
else:
    e2g = display_row.get("e2g_position")
    a1g = display_row.get("a1g_position")
    try:
        auto_min = min(float(e2g), float(a1g)) - peak_padding
        auto_max = max(float(e2g), float(a1g)) + peak_padding
    except (TypeError, ValueError):
        auto_min, auto_max = fallback_x_min, fallback_x_max

xcols = st.columns([1, 1, 2])
x_step = 0.01 if modality == "pl" else 1.0
x_min = xcols[0].number_input("X min", value=float(auto_min), step=x_step)
x_max = xcols[1].number_input("X max", value=float(auto_max), step=x_step)
show_full = xcols[2].checkbox("Show full spectrum", value=False)

if show_full:
    x_min = min(x_for_plot)
    x_max = max(x_for_plot)

render_spectrum_overlay(
    spectrum_id=spectrum_id,
    row=display_row,
    x_raw=x_for_plot,
    y_raw=y_raw,
    x_view_min=float(x_min),
    x_view_max=float(x_max),
    style_cfg=overlay_style_cfg if isinstance(overlay_style_cfg, dict) else None,
    fit_curve_cfg=fit_curve_cfg if isinstance(fit_curve_cfg, dict) else None,
)

render_fit_summary(display_row, download_key=f"download_current_row_{_sanitize_filename(spectrum_id)}")

if "manual_refit_cache" not in st.session_state or not isinstance(st.session_state["manual_refit_cache"], dict):
    st.session_state["manual_refit_cache"] = {}
manual_refit_cache: dict[str, dict[str, Any]] = st.session_state["manual_refit_cache"]
manual_key = _manual_cache_key(report_path=report_path, spectrum_id=spectrum_id)

st.divider()
st.subheader("Manual Refit (PySide6 Editor)")
st.caption("Open external desktop editor for this spectrum, then return and apply single-spectrum refit.")

manual_action_cols = st.columns([2, 1])
open_key = f"open_manual_editor_{_sanitize_filename(report_path.stem)}_{_sanitize_filename(spectrum_id)}"
if manual_action_cols[0].button("Open Manual Editor (Desktop)", use_container_width=True, key=open_key):
    modality = _resolve_modality(payload=payload, row=row, report_path=report_path)
    request_payload = build_editor_request(
        report_path=report_path,
        spectrum_id=spectrum_id,
        modality=modality,
        source_file=str(source_path),
        selected_model=str(display_row.get("selected_model", "")).strip(),
        calibration_offset=0.0,
        row_snapshot=display_row,
        x=[float(v) for v in x_for_plot],
        y=[float(v) for v in y_raw],
    )
    try:
        with tempfile.TemporaryDirectory(prefix="mos2_manual_editor_") as tmpdir:
            request_path = Path(tmpdir) / "request.json"
            editor_output_path = Path(tmpdir) / "editor_response.json"
            request_path.write_text(json.dumps(request_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            with st.spinner("Launching desktop editor. Save and close the editor to continue..."):
                process = _launch_desktop_editor(request_path=request_path, output_path=editor_output_path)

            if process.returncode != 0 and not editor_output_path.exists():
                stderr_text = process.stderr.strip() if process.stderr else ""
                stdout_text = process.stdout.strip() if process.stdout else ""
                debug_text = stderr_text or stdout_text or "No process output available"
                st.error(f"Desktop editor failed (exit={process.returncode}). {debug_text}")
            elif not editor_output_path.exists():
                st.warning("Desktop editor closed without saving. No manual refit was applied.")
            else:
                editor_response = json.loads(editor_output_path.read_text(encoding="utf-8"))
                valid, reason = validate_editor_response(editor_response)
                if not valid:
                    raise ValueError(reason)

                merged_request = dict(request_payload)
                merged_request["selected_model"] = str(
                    editor_response.get("selected_model", request_payload["selected_model"])
                )
                merged_request["peaks"] = editor_response.get("peaks", request_payload.get("peaks", []))
                merged_request["reason"] = str(editor_response.get("reason", "manual_refit_from_desktop"))
                merged_request["operator_note"] = str(editor_response.get("operator_note", ""))

                api = SingleSpectrumRefitAPI(project_root=ROOT)
                refit_payload = api.submit_refit(ManualRefitRequest.from_payload(merged_request))
                after_row = _build_after_row(before_row=display_row, refit_payload=refit_payload)

                override_path = upsert_manual_override(
                    report_json=report_path,
                    spectrum_id=spectrum_id,
                    action_type="manual_refit",
                    selected_model=str(refit_payload.get("selected_model", "")),
                    params=refit_payload.get("params", {}),
                    metrics=refit_payload.get("metrics", {}),
                    fitted_y=refit_payload.get("fitted_y", []),
                    operator_note=str(merged_request.get("operator_note", "")),
                )

                manual_refit_cache[manual_key] = {
                    "after_row": after_row,
                    "refit_payload": refit_payload,
                    "override_path": str(override_path),
                }
                st.success(f"Manual refit applied and saved: {override_path}")
    except Exception as exc:
        st.error(f"Manual refit processing failed: {exc}")

if manual_action_cols[1].button("Clear Manual Result", use_container_width=True):
    if manual_key in manual_refit_cache:
        manual_refit_cache.pop(manual_key, None)
        st.rerun()

manual_state = manual_refit_cache.get(manual_key)
if isinstance(manual_state, dict):
    after_row = manual_state.get("after_row", {})
    if isinstance(after_row, dict) and after_row:
        st.markdown("#### Manual Refit Preview")

        before_metric_cols = st.columns(4)
        before_metric_cols[0].metric("Model (before)", str(display_row.get("selected_model", "NA")))
        before_metric_cols[1].metric("Delta (before)", str(display_row.get("delta_e2g_a1g", "NA")))
        before_metric_cols[2].metric("RMSE (before)", str(display_row.get("rmse", "NA")))
        before_metric_cols[3].metric("AIC (before)", str(display_row.get("aic", "NA")))

        after_metric_cols = st.columns(4)
        after_metric_cols[0].metric("Model (after)", str(after_row.get("selected_model", "NA")))
        after_metric_cols[1].metric("Delta (after)", str(after_row.get("delta_e2g_a1g", "NA")))
        after_metric_cols[2].metric("RMSE (after)", str(after_row.get("rmse", "NA")))
        after_metric_cols[3].metric("AIC (after)", str(after_row.get("aic", "NA")))

        render_spectrum_overlay(
            spectrum_id=f"{spectrum_id} (manual refit)",
            row=after_row,
            x_raw=x_for_plot,
            y_raw=y_raw,
            x_view_min=float(x_min),
            x_view_max=float(x_max),
            style_cfg=overlay_style_cfg if isinstance(overlay_style_cfg, dict) else None,
            fit_curve_cfg=fit_curve_cfg if isinstance(fit_curve_cfg, dict) else None,
        )

        with st.expander("Manual Refit Fit Summary", expanded=False):
            render_fit_summary(after_row, download_key=f"download_manual_row_{_sanitize_filename(spectrum_id)}")

        override_path_text = str(manual_state.get("override_path", "")).strip()
        if override_path_text:
            st.caption(f"Saved override: {override_path_text}")

if candidate_names:
    with st.expander("Candidate Metrics (advanced)", expanded=False):
        candidate_rows = []
        for cand in all_candidates:
            if not isinstance(cand, dict):
                continue
            metrics = cand.get("metrics") or {}
            candidate_rows.append(
                {
                    "model_name": cand.get("model_name"),
                    "fit_status": (cand.get("params") or {}).get("fit_status")
                    if isinstance(cand.get("params"), dict)
                    else None,
                    "aic": metrics.get("aic"),
                    "bic": metrics.get("bic"),
                    "rmse": metrics.get("rmse"),
                    "r2": metrics.get("r2"),
                    "is_valid_candidate": metrics.get("is_valid_candidate"),
                }
            )
        if candidate_rows:
            st.dataframe(pd.DataFrame(candidate_rows), width="stretch")

with st.expander("Filtered Rows Table (advanced)", expanded=False):
    preview_cols = [
        c
        for c in [
            "spectrum_id",
            "source_file",
            "calibration_offset",
            "calibration_success",
            "map_id",
            "map_x",
            "map_y",
            "selected_model",
            "fit_status",
            "e2g_position",
            "a1g_position",
            "delta_e2g_a1g",
            "rmse",
            "r2",
            "aic",
            "bic",
            "attention_score",
            "needs_attention",
        ]
        if c in work_df.columns
    ]
    table = work_df[preview_cols] if preview_cols else work_df
    st.dataframe(table, width="stretch", height=360)

with st.expander("Current Raw Data (advanced)", expanded=False):
    raw_df = pd.DataFrame({"x": x_for_plot, "y": y_raw})
    st.dataframe(raw_df.head(40), width="stretch")
