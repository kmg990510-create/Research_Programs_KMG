"""Page for inspecting and triaging flagged spectra."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys

import streamlit as st

BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(BOOTSTRAP_ROOT) not in sys.path:
    sys.path.append(str(BOOTSTRAP_ROOT))

from fitting.mos2_core.core.runtime_paths import runtime_project_root  # noqa: E402

ROOT = runtime_project_root(__file__, 2)
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from labkit.chrome import panel_title  # noqa: E402
from mos2_gui.components import parameter_editor as _parameter_editor  # noqa: E402
from mos2_gui.components import report_loader as _report_loader  # noqa: E402
from mos2_gui.components.chrome import render_mos2_chrome  # noqa: E402

if not hasattr(_report_loader, "build_projected_csv_bytes"):
    importlib.reload(_report_loader)
if not hasattr(_parameter_editor, "apply_table_edits_to_report"):
    importlib.reload(_parameter_editor)

from mos2_gui.components.parameter_editor import render_changes_download, render_parameter_editor  # noqa: E402
from mos2_gui.components.review_table import render_review_table  # noqa: E402
from mos2_gui.components.science_settings import flagged_legacy_thresholds  # noqa: E402

choose_report_sidebar = _report_loader.choose_report_sidebar
load_graph_config = getattr(_report_loader, "load_graph_config", lambda: {})

render_mos2_chrome("Review", "Review · MoS2 Optical Analysis")
report_path, payload, df = choose_report_sidebar("flagged")

st.header("Review · Flagged Spectra")
st.caption("Heuristic triage view for spectra that may need manual review.")

if report_path is None or payload is None:
    st.stop()
if df.empty:
    st.warning("This report has no spectra rows.")
    st.stop()

flagged = df.copy()
graph_cfg = load_graph_config()
legacy_thresholds = flagged_legacy_thresholds(graph_cfg)
mode_note = "flagged_by_quality_flags"
if "needs_attention" in flagged.columns:
    flagged = flagged[flagged["needs_attention"] == True]  # noqa: E712
elif "quality_flags" in flagged.columns:
    flagged = flagged[
        flagged["quality_flags"].apply(
            lambda v: isinstance(v, list) and len(v) > 0
        )
    ]
else:
    mode_note = "flagged_by_legacy_heuristic"
    with st.container(border=True):
        panel_title("Legacy Triage Thresholds")
        threshold_col1, threshold_col2, threshold_col3 = st.columns(3)
        # Slider start values from config.yaml, clipped to the slider ranges below.
        rmse_default = max(0.0, min(legacy_thresholds["rmse_threshold"], 100.0))
        r2_default = max(0.0, min(legacy_thresholds["r2_lower_bound"], 1.0))
        delta_default = max(10.0, min(legacy_thresholds["delta_max"], 40.0))
        rmse_threshold = threshold_col1.slider("RMSE threshold", 0.0, 100.0, rmse_default, 0.5)
        r2_threshold = threshold_col2.slider("R2 lower bound", 0.0, 1.0, r2_default, 0.001)
        delta_max = threshold_col3.slider("Max delta(E2g-A1g)", 10.0, 40.0, delta_default, 0.5)

    if "rmse" in flagged.columns:
        flagged = flagged[flagged["rmse"] >= rmse_threshold]
    if "r2" in flagged.columns:
        flagged = flagged[flagged["r2"] <= r2_threshold]
    if "delta_e2g_a1g" in flagged.columns:
        flagged = flagged[flagged["delta_e2g_a1g"] >= delta_max]

m_cols = st.columns(4)
m_cols[0].metric("Flagged Rows", len(flagged))
m_cols[1].metric("Total Rows", len(df))
m_cols[2].caption(f"Mode: `{mode_note}`")

if "quality_flags" in flagged.columns:
    reason_counts: dict[str, int] = {}
    for value in flagged["quality_flags"].tolist():
        if not isinstance(value, list):
            continue
        for item in value:
            key = str(item).strip()
            if not key:
                continue
            reason_counts[key] = reason_counts.get(key, 0) + 1
    if reason_counts:
        top_items = sorted(reason_counts.items(), key=lambda item: item[1], reverse=True)[:3]
        reason_cols = st.columns(max(1, len(top_items)))
        for idx, (reason, count) in enumerate(top_items):
            reason_cols[idx].metric(reason, count)

left_col, right_col = st.columns([2, 1], gap="medium")
with left_col, st.container(border=True):
    panel_title("Flagged Candidates")
    render_review_table(flagged, title="")
with right_col, st.container(border=True):
    panel_title("Manual Decision Editor")
    source = flagged if not flagged.empty else df.head(20)
    edited = render_parameter_editor(source, key="flagged_editor")
    render_changes_download(source, edited, file_stem=Path(report_path).stem, report_path=Path(report_path))
