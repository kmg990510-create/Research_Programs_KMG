"""Every page runs without an exception on a synthetic batch, and the edits reach review.json."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from fet_core.review import load_review
from fet_core.synth import transfer_curve
from tests.conftest import write_b1500_csv

GUI = Path(__file__).resolve().parents[1] / "fet_gui"
PAGES = ["Run.py", "pages/1_Devices.py", "pages/2_Compare.py", "pages/3_Finalize.py"]
SECTIONS = {page: ["1) Batch"] for page in PAGES}


def name_of(group: str, position: str) -> str:
    return f"Transfer BG_NFET  [{group}_{position}_BG ; (1) 9_16_2026 12_18_08 AM].csv"


@pytest.fixture
def data_root(tmp_path: Path, device, monkeypatch) -> Path:
    folder = tmp_path / "raw" / "demo"
    folder.mkdir(parents=True)
    write_b1500_csv(folder / name_of("SMP#1", "A1"), transfer_curve(device, -40.0, 60.0, 0.5))
    write_b1500_csv(folder / name_of("SMP#1", "B2"), transfer_curve(replace(device, vth_V=8.0), -40.0, 60.0, 0.5))
    write_b1500_csv(folder / name_of("SMP#2", "C3"), transfer_curve(replace(device, gate_leakage_A=5e-6), -40.0, 60.0, 0.5))
    dead = transfer_curve(device, -40.0, 60.0, 0.5)
    dead["Id"] = 2e-12
    write_b1500_csv(folder / name_of("SMP#2", "D4"), dead)
    monkeypatch.setenv("FET_DATA_ROOT", str(tmp_path))
    return tmp_path


def run_page(page: str) -> AppTest:
    return AppTest.from_file(str(GUI / page), default_timeout=120).run()


def _segmented(at: AppTest, label: str):
    return next(s for s in at.get("button_group") if s.label == label)


@pytest.mark.parametrize("page", PAGES)
def test_page_runs_with_a_batch(data_root: Path, page: str) -> None:
    at = run_page(page)
    assert [str(e.value) for e in at.exception] == []
    sections = [e.label for e in at.sidebar.expander]
    assert sections == SECTIONS[page]
    # Sidebar rule: no widget outside a numbered section.
    assert all(label[0].isdigit() and label[1] == ")" for label in sections)


@pytest.mark.parametrize("page", PAGES)
def test_page_runs_without_any_batch(tmp_path: Path, monkeypatch, page: str) -> None:
    monkeypatch.setenv("FET_DATA_ROOT", str(tmp_path))
    at = run_page(page)
    assert [str(e.value) for e in at.exception] == []
    assert at.info  # tells the user where to start


def test_run_page_stores_batch_geometry(data_root: Path) -> None:
    at = run_page("Run.py")
    width = next(w for w in at.number_input if w.label.startswith("Channel width"))
    width.set_value(20.0)
    next(b for b in at.button if b.label == "Apply").click()
    at.run()
    assert [str(e.value) for e in at.exception] == []
    review = load_review(data_root / "results" / "demo" / "review.json")
    assert review.geometry == {"W_um": 20.0, "L_um": 5.0, "t_ox_nm": 300.0, "eps_r": 3.9}
    assert review.vth_subtract_half_vds is False


def test_devices_decision_is_saved_at_once_and_moves_on(data_root: Path) -> None:
    at = run_page("pages/1_Devices.py")
    listed = at.dataframe[0].value
    # Sweeps that need a look come first, and the first row is drawn.
    assert listed["status"].iloc[0] != "✓" and listed[""].tolist()[0] == "▶"
    first = at.session_state["fet_devices_selected"]
    next(b for b in at.button if b.label == "Reject").click()
    at.run()
    assert [str(e.value) for e in at.exception] == []
    review = load_review(data_root / "results" / "demo" / "review.json")
    assert review.decisions == {first: "rejected"}
    assert at.session_state["fet_devices_selected"] != first  # moved to the next sweep

    next(b for b in at.button if b.label == "Previous").click()
    at.run()
    assert at.session_state["fet_devices_selected"] == first
    note = next(t for t in at.text_input if t.label == "Note")
    note.set_value("probe slipped")
    at.run()
    next(b for b in at.button if b.label == "Clear").click()
    at.run()
    review = load_review(data_root / "results" / "demo" / "review.json")
    assert review.decisions == {} and review.notes == {first: "probe slipped"}


def test_devices_gallery_draws_every_device(data_root: Path) -> None:
    at = run_page("pages/1_Devices.py")
    _segmented(at, "View").set_value("Gallery").run()
    assert [str(e.value) for e in at.exception] == []
    assert not at.dataframe  # the list belongs to the detail view


def test_filters_are_in_body_and_persist_across_stages(data_root: Path) -> None:
    at = AppTest.from_file(str(GUI / "pages/1_Devices.py"), default_timeout=120).run()
    status = next(m for m in at.multiselect if m.label == "Status")
    assert set(status.value) == set(status.options)  # nothing is hidden by default
    assert not at.sidebar.multiselect  # filters live in the body, not the sidebar
    keys = {m.label: m.key for m in at.multiselect}

    other = run_page("pages/2_Compare.py")
    assert {m.label: m.key for m in other.multiselect if m.label in keys} == keys

    # Persistence across stage switch (Devices -> Run -> Compare)
    picked_group = at.multiselect(key="fet_filter_groups").options[:1]
    assert picked_group
    at.multiselect(key="fet_filter_groups").set_value(picked_group).run()
    at.switch_page(str(GUI / "Run.py")).run()
    assert [str(e.value) for e in at.exception] == []
    at.switch_page(str(GUI / "pages/2_Compare.py")).run()
    assert [str(e.value) for e in at.exception] == []
    assert at.multiselect(key="fet_filter_groups").value == picked_group


def test_compare_views_and_immediate_group_edits(data_root: Path) -> None:
    at = run_page("pages/2_Compare.py")
    assert [str(e.value) for e in at.exception] == []
    assert _segmented(at, "Compare view").options == ["Statistics", "Overlay", "Summary table"]
    assert not any(b.label.startswith("Save") for b in at.button)

    # Overlay supports Log / Linear switching cleanly.
    _segmented(at, "Compare view").set_value("Overlay").run()
    assert [str(e.value) for e in at.exception] == []
    _segmented(at, "Current axis scale").set_value("Linear").run()
    assert [str(e.value) for e in at.exception] == []
    layout = json.loads(at.get("plotly_chart")[0].proto.spec)["layout"]
    assert layout["yaxis"]["type"] == "linear"

    # Summary table shows original_group alongside group.
    _segmented(at, "Compare view").set_value("Summary table").run()
    assert [str(e.value) for e in at.exception] == []
    summary_tables = [df.value for df in at.dataframe if "original_group" in df.value.columns]
    assert len(summary_tables) == 1
    assert {"group", "original_group", "n_sweeps", "n_included"} <= set(summary_tables[0].columns)


def test_finalize_writes_the_result_files(data_root: Path) -> None:
    at = run_page("pages/3_Finalize.py")
    next(b for b in at.button if b.label == "Write result files").click()
    at.run()
    assert [str(e.value) for e in at.exception] == []
    out = data_root / "results" / "demo"
    assert (out / "results_summary.csv").exists() and (out / "run_metadata.json").exists()
    assert any(p.name.endswith("_forward.csv") for p in (out / "transfer_curves").iterdir())


@pytest.mark.parametrize("page", ["pages/1_Devices.py", "pages/2_Compare.py"])
def test_every_figure_takes_the_size_from_figure_settings_popover(data_root: Path, page: str) -> None:
    at = run_page(page)
    figures = at.get("plotly_chart")
    assert figures and all(json.loads(f.proto.spec)["layout"].get("width") is None for f in figures)  # default: fit the page
    assert not at.sidebar.number_input  # figure sizes live in Figure settings popover, not sidebar
    for box in at.checkbox:
        if box.label == "Fit width to the page":
            box.set_value(False)
    at.run()
    for field in at.number_input:
        if field.label == "Width (px)":
            assert not field.disabled
            field.set_value(610)
        elif field.label == "Height (px)":
            field.set_value(330)
    at.run()
    assert [str(e.value) for e in at.exception] == []
    layouts = [json.loads(f.proto.spec)["layout"] for f in at.get("plotly_chart")]
    assert layouts and all((layout["width"], layout["height"]) == (610, 330) for layout in layouts)


def test_gallery_size_follows_the_panel_size(data_root: Path) -> None:
    at = run_page("pages/1_Devices.py")
    _segmented(at, "View").set_value("Gallery").run()
    next(f for f in at.number_input if f.label == "Gallery: panels per row").set_value(2)
    at.run()
    layout = json.loads(at.get("plotly_chart")[0].proto.spec)["layout"]
    assert layout.get("width") is None and layout["height"] == 190 * 2 + 94  # 4 devices, 2 per row
