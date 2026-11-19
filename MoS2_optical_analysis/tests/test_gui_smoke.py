"""AppTest smoke and popover tests for the redesigned MoS2 Optical Analysis GUI."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

import mos2_gui  # noqa: F401
from fitting.mos2_core.core.default_stages import build_default_context, build_default_stages
from fitting.mos2_core.core.pipeline import run_pipeline
from fitting.mos2_core.io import generate_dummy_spectra
from fitting.mos2_pl.sample_data import generate_dummy_pl_spectra
from mos2_gui.components import report_loader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GUI_DIR = PROJECT_ROOT / "mos2_gui"


def _clear_report_caches() -> None:
    report_loader.load_report_payload.clear()
    report_loader.load_spectra_dataframe.clear()


def _run_synthetic_reports(tmp_path: Path) -> None:
    raman_ctx = build_default_context(
        run_id="smoke_raman",
        artifact_dir=tmp_path,
        config_dir=PROJECT_ROOT / "fitting" / "mos2_raman" / "config",
    )
    run_pipeline(
        raw_spectra=generate_dummy_spectra(count=4),
        stages=build_default_stages(config=raman_ctx.config),
        context=raman_ctx,
    )

    pl_ctx = build_default_context(
        run_id="smoke_pl",
        artifact_dir=tmp_path,
        config_dir=PROJECT_ROOT / "fitting" / "mos2_pl" / "config",
    )
    run_pipeline(
        raw_spectra=generate_dummy_pl_spectra(count=4),
        stages=build_default_stages(config=pl_ctx.config),
        context=pl_ctx,
    )


def test_figure_settings_popover_controls_grid_format_and_size() -> None:
    from streamlit.testing.v1 import AppTest

    def app() -> None:
        import plotly.graph_objects as go
        import streamlit as st
        import mos2_gui  # noqa: F401
        from mos2_gui.components.figure_sizes import figure_settings_popover, show

        figure_settings_popover(["spectrum"])
        fig = go.Figure(go.Scatter(x=[380.0, 405.0], y=[1.0, 2.0]))
        show(fig, "spectrum", filename="smoke_spec")
        st.session_state["_seen_spec_layout"] = {
            "width": fig.layout.width,
            "height": fig.layout.height,
            "xaxis_showgrid": fig.layout.xaxis.showgrid,
            "yaxis_showgrid": fig.layout.yaxis.showgrid,
        }

    saved_main = sys.modules.get("__main__")
    try:
        at = AppTest.from_function(app, default_timeout=60)
        at.run()
        assert not at.exception
        at.checkbox(key="labkit_figure_grid").check()
        at.radio(key="labkit_figure_image_format").set_value("svg")
        at.checkbox(key="labkit_size_fit_spectrum").uncheck()
        at.run()
        assert not at.exception
        at.number_input(key="labkit_size_width_spectrum").set_value(910)
        at.number_input(key="labkit_size_height_spectrum").set_value(540)
        at.run()
        assert not at.exception
        layout = at.session_state["_seen_spec_layout"]
        assert layout["width"] == 910
        assert layout["height"] == 540
        assert layout["xaxis_showgrid"] is True
        assert layout["yaxis_showgrid"] is True
        assert at.session_state["labkit_figure_image_format"] == "svg"
    finally:
        if saved_main is not None:
            sys.modules["__main__"] = saved_main


@pytest.mark.parametrize(
    "rel_path",
    [
        "Main.py",
        "pages/1_Run_Analysis.py",
        "pages/2_Flagged_Spectra.py",
        "pages/3_All_Spectra_Viewer.py",
        "pages/4_Map_Viewer.py",
        "pages/5_Model_Comparison.py",
        "pages/6_Sample_Comparison.py",
        "pages/7_Finalize.py",
    ],
)
def test_all_mos2_pages_render_without_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rel_path: str
) -> None:
    from streamlit.testing.v1 import AppTest

    _run_synthetic_reports(tmp_path)
    monkeypatch.setattr(report_loader, "project_root", lambda: tmp_path)
    _clear_report_caches()

    saved_main = sys.modules.get("__main__")
    old_cwd = Path.cwd()
    try:
        os.chdir(GUI_DIR)
        at = AppTest.from_file(str(GUI_DIR / rel_path), default_timeout=60)
        at.run()
        assert not at.exception, f"{rel_path} raised: {at.exception}"
    finally:
        os.chdir(old_cwd)
        _clear_report_caches()
        if saved_main is not None:
            sys.modules["__main__"] = saved_main


def test_mos2_body_filters_and_subnavigation_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from streamlit.testing.v1 import AppTest

    _run_synthetic_reports(tmp_path)
    monkeypatch.setattr(report_loader, "project_root", lambda: tmp_path)
    _clear_report_caches()

    saved_main = sys.modules.get("__main__")
    old_cwd = Path.cwd()
    try:
        os.chdir(GUI_DIR)
        at = AppTest.from_file(str(GUI_DIR / "pages/3_All_Spectra_Viewer.py"), default_timeout=60)
        at.run()
        assert not at.exception
        # Sidebar should only contain 1) Report, not 2) Filters
        assert not any("Filters" in str(el.label) for el in at.sidebar.expander if hasattr(el, "label"))
        assert "mos2_stage_Viewer" in at.session_state
        assert "mos2_viewer_sub_Spectra" in at.session_state
        assert at.session_state["mos2_viewer_sub_last"] == "Spectra"
        at.text_input(key="all_spectra_search").set_value("spec").run()
        assert not at.exception

        cmp_at = AppTest.from_file(str(GUI_DIR / "pages/5_Model_Comparison.py"), default_timeout=60)
        cmp_at.run()
        assert not cmp_at.exception
        cmp_at.checkbox(key="model_cmp_hide_rejected").check().run()
        assert not cmp_at.exception
        assert cmp_at.session_state[report_loader.FILTER_STORE_KEY]["hide_rejected"] is True
    finally:
        os.chdir(old_cwd)
        _clear_report_caches()
        if saved_main is not None:
            sys.modules["__main__"] = saved_main


def test_sample_comparison_raman_renders_without_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from streamlit.testing.v1 import AppTest

    for idx in (1, 2):
        raman_ctx = build_default_context(
            run_id=f"smoke_raman_{idx}",
            artifact_dir=tmp_path,
            config_dir=PROJECT_ROOT / "fitting" / "mos2_raman" / "config",
        )
        run_pipeline(
            raw_spectra=generate_dummy_spectra(count=4),
            stages=build_default_stages(config=raman_ctx.config),
            context=raman_ctx,
        )
    monkeypatch.setattr(report_loader, "project_root", lambda: tmp_path)
    _clear_report_caches()

    saved_main = sys.modules.get("__main__")
    old_cwd = Path.cwd()
    try:
        os.chdir(GUI_DIR)
        at = AppTest.from_file(str(GUI_DIR / "pages/6_Sample_Comparison.py"), default_timeout=60)
        at.run()
        assert not at.exception
        assert len(at.get("plotly_chart")) >= 2
    finally:
        os.chdir(old_cwd)
        _clear_report_caches()
        if saved_main is not None:
            sys.modules["__main__"] = saved_main
