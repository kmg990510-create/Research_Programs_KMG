"""Stage navigation and masthead chrome helpers for MoS2 Optical Analysis."""

from __future__ import annotations

import streamlit as st

from labkit.chrome import is_unified_mode, render_masthead, render_stage_header, render_subnav, resolve_page

VIEWER_SUB_STORE_KEY = "mos2_viewer_sub_last"
COMPARE_SUB_STORE_KEY = "mos2_compare_sub_last"


def _viewer_target() -> object:
    last = st.session_state.get(VIEWER_SUB_STORE_KEY, "Spectra")
    if last == "Map":
        return resolve_page("mos2", "map", "pages/4_Map_Viewer.py")
    return resolve_page("mos2", "spectra", "pages/3_All_Spectra_Viewer.py")


def _compare_target() -> object:
    last = st.session_state.get(COMPARE_SUB_STORE_KEY, "Models")
    if last == "Samples":
        return resolve_page("mos2", "samples", "pages/6_Sample_Comparison.py")
    return resolve_page("mos2", "models", "pages/5_Model_Comparison.py")


def render_mos2_chrome(
    active_stage: str,
    page_title: str,
    *,
    viewer_sub: str | None = None,
    compare_sub: str | None = None,
) -> None:
    """Render standalone page config, fixed masthead, program title, and stage/sub-view bars."""
    if not is_unified_mode():
        st.set_page_config(page_title=page_title, layout="wide")
        render_masthead("MoS₂ Optical Analysis · Raman / PL")

    if viewer_sub in {"Spectra", "Map"}:
        st.session_state[VIEWER_SUB_STORE_KEY] = viewer_sub
    if compare_sub in {"Models", "Samples"}:
        st.session_state[COMPARE_SUB_STORE_KEY] = compare_sub

    stages = (
        ("Overview", resolve_page("mos2", "overview", "Main.py")),
        ("Run", resolve_page("mos2", "run", "pages/1_Run_Analysis.py")),
        ("Review", resolve_page("mos2", "flagged", "pages/2_Flagged_Spectra.py")),
        ("Viewer", _viewer_target()),
        ("Compare", _compare_target()),
        ("Finalize", resolve_page("mos2", "finalize", "pages/7_Finalize.py")),
    )
    render_stage_header("MoS₂ Optical Analysis", stages, active_stage, key_prefix="mos2_stage")

    if viewer_sub is not None:
        render_subnav(
            "Viewer mode",
            (
                ("Spectra", resolve_page("mos2", "spectra", "pages/3_All_Spectra_Viewer.py")),
                ("Map", resolve_page("mos2", "map", "pages/4_Map_Viewer.py")),
            ),
            viewer_sub,
            key_prefix="mos2_viewer_sub",
        )
    if compare_sub is not None:
        render_subnav(
            "Compare mode",
            (
                ("Models", resolve_page("mos2", "models", "pages/5_Model_Comparison.py")),
                ("Samples", resolve_page("mos2", "samples", "pages/6_Sample_Comparison.py")),
            ),
            compare_sub,
            key_prefix="mos2_compare_sub",
        )
