"""Unified Streamlit entry point for Research_Programs_KMG."""

from __future__ import annotations

from pathlib import Path
import sys

import streamlit as st

ROOT = Path(__file__).resolve().parent
for _path_entry in (
    ROOT,
    ROOT / "MoS2_optical_analysis",
    ROOT / "FET_analysis",
    ROOT / "MoS2_adsorption_sim",
):
    _path_str = str(_path_entry)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

st.set_page_config(page_title="Research Programs KMG", layout="wide")


_ACTIVE_PROGRAM_KEY = "hub_active_program"
_SWITCH_TO_KEY = "hub_switch_to"


def _select_program(program_id: str) -> None:
    st.session_state[_ACTIVE_PROGRAM_KEY] = program_id
    st.session_state[_SWITCH_TO_KEY] = program_id
    st.rerun()


def _hub_page() -> None:
    """Render the unified landing hub to switch between lab programs."""
    if st.session_state.get(_ACTIVE_PROGRAM_KEY) is not None:
        st.session_state[_ACTIVE_PROGRAM_KEY] = None
        st.rerun()

    st.title("Research Programs KMG")
    st.caption(
        "Select a research program below. Only the selected program's pages will appear in the sidebar."
    )

    col_mos2, col_fet, col_ads = st.columns(3)

    with col_mos2.container(border=True):
        st.subheader("MoS2 Optical Analysis")
        st.write(
            "Raman and PL spectrum peak fitting, automated/manual review, "
            "spatial map inspection, and strain/doping sample comparison."
        )
        if st.button(
            "Open MoS2 Optical Analysis",
            key="hub_open_mos2",
            type="primary",
            use_container_width=True,
        ):
            _select_program("mos2")

    with col_fet.container(border=True):
        st.subheader("FET Analysis")
        st.write(
            "Transfer and output characterization, quality flag review, "
            "device/group comparison, and reproducible export."
        )
        if st.button(
            "Open FET Analysis",
            key="hub_open_fet",
            type="primary",
            use_container_width=True,
        ):
            _select_program("fet")

    with col_ads.container(border=True):
        st.subheader("MoS2 Adsorption Sim")
        st.write(
            "MLIP adsorption relaxation, pose inspection, energy decomposition "
            "and site comparisons, and structure export."
        )
        if st.button(
            "Open MoS2 Adsorption Sim",
            key="hub_open_ads",
            type="primary",
            use_container_width=True,
        ):
            _select_program("ads")


_MOS2_GUI_DIR = ROOT / "MoS2_optical_analysis" / "mos2_gui"
_FET_GUI_DIR = ROOT / "FET_analysis" / "fet_gui"
_ADS_GUI_DIR = ROOT / "MoS2_adsorption_sim" / "ads_gui"

_MOS2_ENTRY = st.Page(
    str(_MOS2_GUI_DIR / "Main.py"),
    title="Overview",
    url_path="mos2_overview",
)
_FET_ENTRY = st.Page(
    str(_FET_GUI_DIR / "Run.py"),
    title="Run",
    url_path="fet_run",
)
_ADS_ENTRY = st.Page(
    str(_ADS_GUI_DIR / "Run.py"),
    title="Run",
    url_path="ads_run",
)

_PROGRAM_SECTIONS: dict[str, tuple[str, st.Page, list[st.Page]]] = {
    "mos2": (
        "MoS2 Optical Analysis",
        _MOS2_ENTRY,
        [
            _MOS2_ENTRY,
            st.Page(
                str(_MOS2_GUI_DIR / "pages" / "1_Run_Analysis.py"),
                title="1 Run Analysis",
                url_path="mos2_run",
            ),
            st.Page(
                str(_MOS2_GUI_DIR / "pages" / "2_Flagged_Spectra.py"),
                title="2 Flagged Spectra",
                url_path="mos2_flagged",
            ),
            st.Page(
                str(_MOS2_GUI_DIR / "pages" / "3_All_Spectra_Viewer.py"),
                title="3 All Spectra Viewer",
                url_path="mos2_spectra",
            ),
            st.Page(
                str(_MOS2_GUI_DIR / "pages" / "4_Map_Viewer.py"),
                title="4 Map Viewer",
                url_path="mos2_map",
            ),
            st.Page(
                str(_MOS2_GUI_DIR / "pages" / "5_Model_Comparison.py"),
                title="5 Model Comparison",
                url_path="mos2_models",
            ),
            st.Page(
                str(_MOS2_GUI_DIR / "pages" / "6_Sample_Comparison.py"),
                title="6 Sample Comparison",
                url_path="mos2_samples",
            ),
            st.Page(
                str(_MOS2_GUI_DIR / "pages" / "7_Finalize.py"),
                title="7 Finalize",
                url_path="mos2_finalize",
            ),
        ],
    ),
    "fet": (
        "FET Analysis",
        _FET_ENTRY,
        [
            _FET_ENTRY,
            st.Page(
                str(_FET_GUI_DIR / "pages" / "1_Devices.py"),
                title="1 Devices",
                url_path="fet_devices",
            ),
            st.Page(
                str(_FET_GUI_DIR / "pages" / "2_Compare.py"),
                title="2 Compare",
                url_path="fet_compare",
            ),
            st.Page(
                str(_FET_GUI_DIR / "pages" / "3_Finalize.py"),
                title="3 Finalize",
                url_path="fet_finalize",
            ),
        ],
    ),
    "ads": (
        "MoS2 Adsorption Sim",
        _ADS_ENTRY,
        [
            _ADS_ENTRY,
            st.Page(
                str(_ADS_GUI_DIR / "pages" / "1_Poses.py"),
                title="1 Poses",
                url_path="ads_poses",
            ),
            st.Page(
                str(_ADS_GUI_DIR / "pages" / "2_Compare.py"),
                title="2 Compare",
                url_path="ads_compare",
            ),
            st.Page(
                str(_ADS_GUI_DIR / "pages" / "3_Finalize.py"),
                title="3 Finalize",
                url_path="ads_finalize",
            ),
        ],
    ),
}

_active_program = st.session_state.get(_ACTIVE_PROGRAM_KEY)
_hub_entry = st.Page(
    _hub_page,
    title="Program Hub",
    url_path="hub",
    default=_active_program not in _PROGRAM_SECTIONS,
)

if _active_program in _PROGRAM_SECTIONS:
    _section_title, _entry_page, _section_pages = _PROGRAM_SECTIONS[_active_program]
    _nav_pages = {
        "Program Hub": [_hub_entry],
        _section_title: _section_pages,
    }
else:
    _nav_pages = {
        "Program Hub": [_hub_entry],
    }

pg = st.navigation(_nav_pages)
_pending = st.session_state.pop(_SWITCH_TO_KEY, None)
if _pending in _PROGRAM_SECTIONS:
    st.switch_page(_PROGRAM_SECTIONS[_pending][1])
pg.run()
