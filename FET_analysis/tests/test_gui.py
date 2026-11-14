"""Every page runs without an exception on a synthetic batch, and the edits reach review.json."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from fet_core.review import load_review
from fet_core.synth import transfer_curve
from tests.conftest import write_b1500_csv

GUI = Path(__file__).resolve().parents[1] / "gui"
PAGES = ["Run.py", "pages/1_Devices.py", "pages/2_Compare.py", "pages/3_Finalize.py"]
SECTIONS = {
    "Run.py": ["1) Batch"],
    "pages/1_Devices.py": ["1) Batch", "2) Filters"],
    "pages/2_Compare.py": ["1) Batch", "2) Filters"],
    "pages/3_Finalize.py": ["1) Batch"],
}


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


@pytest.mark.parametrize("page", PAGES)
def test_page_runs_with_a_batch(data_root: Path, page: str) -> None:
    at = run_page(page)
    assert [str(e.value) for e in at.exception] == []
    sections = [e.label for e in at.sidebar.expander]
    assert sections == SECTIONS[page]
    # sidebar rule: no widget outside a numbered section
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
    # sweeps that need a look come first, and the first row is the one drawn
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
    at.radio[0].set_value("Gallery")
    at.run()
    assert [str(e.value) for e in at.exception] == []
    assert not at.dataframe  # the list belongs to the detail view


def test_filters_are_shared_between_pages(data_root: Path) -> None:
    at = run_page("pages/1_Devices.py")
    status = next(m for m in at.multiselect if m.label == "Status")
    assert set(status.value) == set(status.options)  # nothing is hidden by default
    keys = {m.label: m.key for m in at.multiselect}
    other = run_page("pages/2_Compare.py")
    assert {m.label: m.key for m in other.sidebar.multiselect} == keys


def test_compare_saves_group_names_at_once(data_root: Path) -> None:
    at = run_page("pages/2_Compare.py")
    assert [str(e.value) for e in at.exception] == []
    assert [t.label for t in at.tabs] == ["Statistics", "Overlay", "Summary table", "Group names and order"]
    assert not any(b.label.startswith("Save") for b in at.button)


def test_finalize_writes_the_result_files(data_root: Path) -> None:
    at = run_page("pages/3_Finalize.py")
    next(b for b in at.button if b.label == "Write result files").click()
    at.run()
    assert [str(e.value) for e in at.exception] == []
    out = data_root / "results" / "demo"
    assert (out / "results_summary.csv").exists() and (out / "run_metadata.json").exists()
    assert any(p.name.endswith("_forward.csv") for p in (out / "transfer_curves").iterdir())
