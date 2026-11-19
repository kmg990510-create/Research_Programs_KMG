"""Unified Streamlit entry point for Research_Programs_KMG."""

from __future__ import annotations

import html
import os
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

from labkit.chrome import (  # noqa: E402
    ACTIVE_PROGRAM_KEY,
    HUB_PAGE_MAP_KEY,
    UNIFIED_MODE_KEY,
    panel_title,
    render_masthead,
    render_program_switcher,
)

st.set_page_config(page_title="Research Programs KMG", layout="wide")


def _optical_inventory() -> str:
    results_dir = ROOT / "MoS2_optical_analysis" / "data" / "results"
    reports: list[Path] = []
    for modality in ("raman", "pl"):
        rep_dir = results_dir / modality / "reports"
        if rep_dir.is_dir():
            reports.extend(rep_dir.rglob("*_fit_report.json"))
    if not reports:
        return "Reports: 0 on disk<br>Run Raman/PL pipeline to begin"
    latest = max(reports, key=lambda p: p.stat().st_mtime).stem.removesuffix("_fit_report")
    return f"Reports: <strong>{len(reports)}</strong> on disk<br>Latest: {html.escape(latest)}"


def _fet_inventory() -> str:
    raw_dir = Path(os.environ.get("FET_DATA_ROOT", ROOT / "FET_analysis" / "data")) / "raw"
    batches = (
        sorted(p.name for p in raw_dir.iterdir() if p.is_dir() and any(f.is_file() for f in p.iterdir()))
        if raw_dir.is_dir()
        else []
    )
    if not batches:
        return "Batches: 0 in data/raw<br>Add B1500/4200A files in Run"
    return f"Batches: <strong>{len(batches)}</strong> in data/raw<br>Latest: {html.escape(batches[-1])}"


def _ads_inventory() -> str:
    results_dir = Path(os.environ.get("ADS_DATA_ROOT", ROOT / "MoS2_adsorption_sim" / "data")) / "results"
    if not results_dir.is_dir():
        return "Batches: 0 in data/results<br>Run MLIP screening in Run"
    batches = sorted(p.name for p in results_dir.iterdir() if p.is_dir() and (p / "batch_state.json").is_file())
    studies = sorted(p.name for p in results_dir.iterdir() if p.is_dir() and (p / "coverage_summary.csv").is_file())
    if not batches and not studies:
        return "Batches: 0 in data/results<br>Run MLIP screening in Run"
    latest = (batches or studies)[-1]
    return f"Batches: <strong>{len(batches)}</strong> · Studies: <strong>{len(studies)}</strong><br>Latest: {html.escape(latest)}"


def _masthead_status(active_program: str) -> str:
    labels = {
        "hub": "Unified Workspace · 3 Lab Programs",
        "mos2": "MoS₂ Optical Analysis · Raman / PL",
        "fet": "FET Analysis · Transfer Review",
        "ads": "MoS₂ Adsorption Sim · uMLIP + DFT-D3",
    }
    return labels.get(active_program, labels["hub"])


def _hub_page() -> None:
    """Render the unified Program Hub without synthetic demo numbers."""
    st.title("Program Hub")
    st.caption("Select a program to open its workspace.")

    cards_specs = (
        (
            "mos2",
            "MoS₂ Optical Analysis",
            "Raman and PL spectrum peak fitting, automated/manual review, spatial maps, and strain/doping comparison.",
            _optical_inventory(),
            "hub_open_mos2",
        ),
        (
            "fet",
            "FET Analysis",
            "Transfer curve characterization, automated quality checks, device review, and reproducible CSV export.",
            _fet_inventory(),
            "hub_open_fet",
        ),
        (
            "ads",
            "MoS₂ Adsorption Sim",
            "MLIP + DFT-D3 adsorption relaxation, 3D pose review, binding/energy decomposition, and coverage studies.",
            _ads_inventory(),
            "hub_open_ads",
        ),
    )

    with st.container(key="kmg_hub_cards"):
        columns = st.columns(3, gap="medium")
        for col, (prog_id, title, hint, meta_html, btn_key) in zip(columns, cards_specs):
            with col, st.container(border=True):
                panel_title(title)
                st.html(
                    f'<p class="kmg-card-hint">{html.escape(hint)}</p>'
                    f'<div class="kmg-card-meta">{meta_html}</div>'
                )
                if st.button(
                    "Open",
                    icon=":material/arrow_forward:",
                    width="stretch",
                    key=btn_key,
                ):
                    st.switch_page(_ENTRY_BY_PROGRAM[prog_id])

    with st.container(border=True):
        panel_title("Data Sources")
        st.table(
            [
                {"Program": "MoS₂ Optical Analysis", "Formats": "TXT, ASC, Mapping CSV", "Contents": "Raman & PL spectra, spatial map coordinates"},
                {"Program": "FET Analysis", "Formats": "B1500 CSV, Clarius XLS", "Contents": "Transfer Vg-Id-Ig sweeps & measurement settings"},
                {"Program": "MoS₂ Adsorption Sim", "Formats": "XYZ, MOL, SDF, YAML", "Contents": "2H-MoS₂ slabs, adsorbate poses, MD & coverage trajectories"},
            ]
        )


_MOS2_GUI_DIR = ROOT / "MoS2_optical_analysis" / "mos2_gui"
_FET_GUI_DIR = ROOT / "FET_analysis" / "fet_gui"
_ADS_GUI_DIR = ROOT / "MoS2_adsorption_sim" / "ads_gui"

_HUB_ENTRY = st.Page(_hub_page, title="Program Hub", url_path="hub", default=True)

_MOS2_PAGES = {
    "overview": st.Page(str(_MOS2_GUI_DIR / "Main.py"), title="Overview", url_path="mos2_overview"),
    "run": st.Page(str(_MOS2_GUI_DIR / "pages" / "1_Run_Analysis.py"), title="Run Analysis", url_path="mos2_run"),
    "flagged": st.Page(str(_MOS2_GUI_DIR / "pages" / "2_Flagged_Spectra.py"), title="Flagged Spectra", url_path="mos2_flagged"),
    "spectra": st.Page(str(_MOS2_GUI_DIR / "pages" / "3_All_Spectra_Viewer.py"), title="Spectra Viewer", url_path="mos2_spectra"),
    "map": st.Page(str(_MOS2_GUI_DIR / "pages" / "4_Map_Viewer.py"), title="Map Viewer", url_path="mos2_map"),
    "models": st.Page(str(_MOS2_GUI_DIR / "pages" / "5_Model_Comparison.py"), title="Model Comparison", url_path="mos2_models"),
    "samples": st.Page(str(_MOS2_GUI_DIR / "pages" / "6_Sample_Comparison.py"), title="Sample Comparison", url_path="mos2_samples"),
    "finalize": st.Page(str(_MOS2_GUI_DIR / "pages" / "7_Finalize.py"), title="Finalize", url_path="mos2_finalize"),
}

_FET_PAGES = {
    "run": st.Page(str(_FET_GUI_DIR / "Run.py"), title="Run", url_path="fet_run"),
    "devices": st.Page(str(_FET_GUI_DIR / "pages" / "1_Devices.py"), title="Devices", url_path="fet_devices"),
    "compare": st.Page(str(_FET_GUI_DIR / "pages" / "2_Compare.py"), title="Compare", url_path="fet_compare"),
    "finalize": st.Page(str(_FET_GUI_DIR / "pages" / "3_Finalize.py"), title="Finalize", url_path="fet_finalize"),
}

_ADS_PAGES = {
    "run": st.Page(str(_ADS_GUI_DIR / "Run.py"), title="Run", url_path="ads_run"),
    "poses": st.Page(str(_ADS_GUI_DIR / "pages" / "1_Poses.py"), title="Poses", url_path="ads_poses"),
    "coverage": st.Page(str(_ADS_GUI_DIR / "pages" / "4_Coverage_Dimer.py"), title="Coverage & Dimer", url_path="ads_coverage"),
    "compare": st.Page(str(_ADS_GUI_DIR / "pages" / "2_Compare.py"), title="Compare", url_path="ads_compare"),
    "finalize": st.Page(str(_ADS_GUI_DIR / "pages" / "3_Finalize.py"), title="Finalize", url_path="ads_finalize"),
}

_ENTRY_BY_PROGRAM: dict[str, st.Page] = {
    "hub": _HUB_ENTRY,
    "mos2": _MOS2_PAGES["overview"],
    "fet": _FET_PAGES["run"],
    "ads": _ADS_PAGES["run"],
}

_PAGE_MAP: dict[tuple[str, str], st.Page] = {
    ("hub", "hub"): _HUB_ENTRY,
    **{("mos2", key): page for key, page in _MOS2_PAGES.items()},
    **{("fet", key): page for key, page in _FET_PAGES.items()},
    **{("ads", key): page for key, page in _ADS_PAGES.items()},
}

st.session_state[UNIFIED_MODE_KEY] = True
st.session_state[HUB_PAGE_MAP_KEY] = _PAGE_MAP

pg = st.navigation(
    [_HUB_ENTRY, *_MOS2_PAGES.values(), *_FET_PAGES.values(), *_ADS_PAGES.values()],
    position="hidden",
)

_url = str(getattr(pg, "url_path", "") or "")
if _url.startswith("mos2_"):
    _active_program = "mos2"
elif _url.startswith("fet_"):
    _active_program = "fet"
elif _url.startswith("ads_"):
    _active_program = "ads"
else:
    _active_program = "hub"

st.session_state[ACTIVE_PROGRAM_KEY] = _active_program
render_masthead(_masthead_status(_active_program))
_picked_program = render_program_switcher(_active_program)
if _picked_program is not None and _picked_program != _active_program:
    st.switch_page(_ENTRY_BY_PROGRAM[_picked_program])

pg.run()
