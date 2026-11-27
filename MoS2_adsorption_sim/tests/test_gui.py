"""Automated Streamlit GUI tests (AppTest) and architecture contracts for MoS2_adsorption_sim."""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest
from streamlit.testing.v1 import AppTest

from ads_core.config import load_config
from ads_core.model import ORIENTATION_ANCHOR_DOWN, ORIENTATION_FLAT, SITE_HOLLOW, SITE_S_TOP, SITE_VS
from ads_core.pipeline import run_batch
from ads_core.report.export import (
    BATCH_STATE_FILE,
    MD_CURVES_DIR,
    MD_SUMMARY_FILE,
    METADATA_FILE,
    MOLECULES_FILE,
    POSES_FILE,
    STRUCTURES_DIR,
    export_run,
)
from ads_core.review import load_review
from ads_core.simulation.quality import REASONS, REASON_MESSAGES
from ads_gui.components.atoms2d import pose_top_side_png, slab_sites_png
from ads_gui.components.viewer3d import md_3d_html, pose_3d_html

GUI = Path(__file__).resolve().parents[1] / "ads_gui"
ADS_CORE = Path(__file__).resolve().parents[1] / "ads_core"
COMPONENTS = GUI / "components"

PAGES = ["Run.py", "pages/1_Poses.py", "pages/2_Compare.py", "pages/3_Finalize.py"]
SECTIONS = {page: ["1) Batch"] for page in PAGES}


def _segmented(at: AppTest, label: str):
    return next(s for s in at.get("button_group") if s.label == label)


@pytest.fixture(scope="module")
def _seed_batches(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build synthetic seed batches once per module, copied per test to avoid slow reruns."""
    seed_root = tmp_path_factory.mktemp("ads_seed")
    cfg = load_config()
    results = seed_root / "results"

    # 1. Batch with attention poses (d3_enabled=False -> repulsive_adsorption on basal plane)
    run_attn = run_batch(
        "01_no_d3_attn",
        cfg,
        surfaces=["pristine_2x2"],
        molecules=["H2O"],
        backend="synth_morse",
        d3_enabled=False,
        site_types=[SITE_HOLLOW, SITE_S_TOP],
        orientations=[ORIENTATION_FLAT],
        azimuth_angles_deg=[0.0],
        scan_binding_curves=False,
    )
    export_run(run_attn, None, results / "01_no_d3_attn")

    # 2. Primary D3-enabled batch (pristine physisorption + V_S chemisorption + 1D binding curves)
    run_main = run_batch(
        "02_demo_d3",
        cfg,
        surfaces=["pristine_2x2", "V_S_2x2"],
        molecules=["H2O"],
        backend="synth_morse",
        d3_enabled=True,
        site_types=[SITE_HOLLOW, SITE_S_TOP, SITE_VS],
        orientations=[ORIENTATION_FLAT, ORIENTATION_ANCHOR_DOWN],
        azimuth_angles_deg=[0.0],
        scan_binding_curves=True,
    )
    export_run(run_main, None, results / "02_demo_d3")
    return seed_root


@pytest.fixture
def data_root(_seed_batches: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Copy seed batches into an isolated temporary ADS_DATA_ROOT for each test."""
    shutil.copytree(_seed_batches / "results", tmp_path / "results")
    monkeypatch.setenv("ADS_DATA_ROOT", str(tmp_path))
    return tmp_path


def run_page(page: str) -> AppTest:
    return AppTest.from_file(str(GUI / page), default_timeout=120).run()


def test_reason_messages_cover_all_registered_reasons() -> None:
    assert set(REASON_MESSAGES) == set(REASONS)
    assert all(isinstance(v, str) and len(v.strip()) > 5 for v in REASON_MESSAGES.values())


def test_no_streamlit_import_in_core_or_components() -> None:
    pattern = re.compile(r"^\s*(import|from)\s+streamlit\b", re.MULTILINE)
    for folder in (ADS_CORE, COMPONENTS):
        for py_file in folder.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            assert not pattern.search(content), f"{py_file} must not import streamlit"


def test_gui_pages_stay_under_400_lines() -> None:
    for page in (*PAGES, "pages/4_Coverage_Dimer.py"):
        path = GUI / page
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) < 400, f"{page} has {len(lines)} lines (limit: < 400)"


def test_viewer3d_and_atoms2d_outputs_without_streamlit(data_root: Path) -> None:
    from ads_core.report.export import load_batch_run

    run = load_batch_run(data_root / "results" / "02_demo_d3")
    res = run.results[0]
    art = run.artifacts[res.pose_id]

    html_ghost = pose_3d_html(art, res, mode="relaxed_with_ghost")
    assert "<div" in html_ghost and "d_min" in html_ghost

    html_traj = pose_3d_html(art, res, mode="trajectory")
    assert "<div" in html_traj

    png_2d = pose_top_side_png(art.relaxed_atoms, title=res.pose_id, status=res.status)
    assert png_2d.startswith(b"\x89PNG")

    first_slab = next(iter(run.slabs.values()))
    png_sites = slab_sites_png(first_slab, run.config)
    assert png_sites.startswith(b"\x89PNG")


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_without_batches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, page: str) -> None:
    monkeypatch.setenv("ADS_DATA_ROOT", str(tmp_path))
    at = run_page(page)
    assert [str(e.value) for e in at.exception] == []
    assert [e.label for e in at.sidebar.expander] == ["1) Batch"]
    assert at.info


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_with_batch(data_root: Path, page: str) -> None:
    at = run_page(page)
    assert [str(e.value) for e in at.exception] == []
    sections = [e.label for e in at.sidebar.expander]
    assert sections == SECTIONS[page]
    assert all(label[0].isdigit() and label[1] == ")" for label in sections)


def test_run_page_can_create_and_run_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADS_DATA_ROOT", str(tmp_path))
    at = run_page("Run.py")
    assert [str(e.value) for e in at.exception] == []

    # Open Advanced options and run a minimal 2x2 single-site single-orientation batch cleanly
    next(c for c in at.checkbox if c.label == "Advanced pose & optimizer settings").set_value(True)
    at.run()
    assert [str(e.value) for e in at.exception] == []

    next(t for t in at.text_input if t.label == "Batch name").set_value("ui_batch")
    next(m for m in at.multiselect if m.label == "Surfaces").set_value(["pristine"])
    next(m for m in at.multiselect if m.label == "Preset molecules").set_value(["H2O"])
    next(n for n in at.number_input if n.label == "Supercell nx").set_value(2)
    next(n for n in at.number_input if n.label == "Supercell ny").set_value(2)
    next(m for m in at.multiselect if m.label == "Restrict sites (empty = all)").set_value(["Hollow"])
    next(m for m in at.multiselect if m.label == "Orientations").set_value(["flat"])
    next(m for m in at.multiselect if m.label == "Azimuth angles (deg)").set_value([0.0])
    at.run()

    next(b for b in at.button if b.label == "Run simulation batch").click()
    at.run()
    assert [str(e.value) for e in at.exception] == []

    out_dir = tmp_path / "results" / "ui_batch"
    assert (out_dir / BATCH_STATE_FILE).is_file()
    assert (out_dir / POSES_FILE).is_file()
    assert len(at.metric) == 5


def test_poses_page_approve_reject_clear_and_note(data_root: Path) -> None:
    at = run_page("pages/1_Poses.py")
    # Switch sidebar batch to 01_no_d3_attn to verify attention poses rank first
    next(s for s in at.sidebar.selectbox if s.label == "Simulation batch").set_value("01_no_d3_attn")
    at.run()
    assert [str(e.value) for e in at.exception] == []

    listed = at.dataframe[0].value
    assert listed["status"].iloc[0] == "⚠" and listed[""].iloc[0] == "▶"
    first = at.session_state["poses_selected"]

    next(b for b in at.button if b.label == "Reject").click()
    at.run()
    assert [str(e.value) for e in at.exception] == []
    review = load_review(data_root / "results" / "01_no_d3_attn" / "review.json")
    assert review.decisions == {first: "rejected"}
    assert at.session_state["poses_selected"] != first

    next(b for b in at.button if b.label == "Previous").click()
    at.run()
    assert at.session_state["poses_selected"] == first

    next(t for t in at.text_input if t.label == "Note").set_value("No D3 repulsive artifact")
    at.run()
    next(b for b in at.button if b.label == "Clear").click()
    at.run()
    review = load_review(data_root / "results" / "01_no_d3_attn" / "review.json")
    assert review.decisions == {} and review.notes == {first: "No D3 repulsive artifact"}

    next(b for b in at.button if b.label == "Approve").click()
    at.run()
    review = load_review(data_root / "results" / "01_no_d3_attn" / "review.json")
    assert review.decisions == {first: "approved"}


def test_poses_gallery_and_3d_viewer_modes(data_root: Path) -> None:
    at = run_page("pages/1_Poses.py")
    next(r for r in at.radio if r.label == "3D View").set_value("Relaxation Trajectory Animation")
    at.run()
    assert [str(e.value) for e in at.exception] == []

    _segmented(at, "View").set_value("Gallery").run()
    next(n for n in at.number_input if n.label == "Gallery: panels per row").set_value(2)
    at.run()
    assert [str(e.value) for e in at.exception] == []
    assert not at.dataframe  # pose selection table belongs to Detail view
    layout = json.loads(at.get("plotly_chart")[0].proto.spec)["layout"]
    assert layout.get("width") is None and layout["height"] == 200 * 5 + 94  # 10 poses, 2 per row -> 5 rows


def test_filters_shared_between_poses_and_compare(data_root: Path) -> None:
    at = run_page("Run.py")
    at.switch_page("pages/1_Poses.py").run()
    assert [str(e.value) for e in at.exception] == []
    status_ms = next(m for m in at.multiselect if m.label == "Status")
    assert set(status_ms.value) == set(status_ms.options)
    assert not at.sidebar.multiselect
    poses_keys = {m.label: m.key for m in at.multiselect}

    at.multiselect(key="ads_filter_status").set_value(["valid"]).run()
    at.switch_page("Run.py").run()
    assert [str(e.value) for e in at.exception] == []
    at.switch_page("pages/2_Compare.py").run()
    assert [str(e.value) for e in at.exception] == []
    assert at.multiselect(key="ads_filter_status").value == ["valid"]
    assert {m.label: m.key for m in at.multiselect if m.label in poses_keys} == poses_keys
    assert _segmented(at, "Compare view").options == [
        "Statistics",
        "Energy & Binding Curves",
        "Surface Site Map",
        "Summary table",
    ]
    _segmented(at, "Compare view").set_value("Summary table").run()
    assert [str(e.value) for e in at.exception] == []
    assert any("group_key" in df.value.columns for df in at.dataframe)


@pytest.mark.parametrize("page", ["pages/1_Poses.py", "pages/2_Compare.py"])
def test_figure_size_controls_are_in_figure_settings_popover(data_root: Path, page: str) -> None:
    at = run_page(page)
    figures = at.get("plotly_chart")
    assert figures and all(json.loads(f.proto.spec)["layout"].get("width") is None for f in figures)
    assert not at.sidebar.number_input  # figure sizes live in Figure settings popover, not sidebar

    for box in at.checkbox:
        if box.label == "Grid":
            box.set_value(True)
        elif box.label == "Fit width to the page":
            box.set_value(False)
    next(r for r in at.radio if r.label == "Image format").set_value("svg")
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
    assert all(layout["xaxis"]["showgrid"] is True for layout in layouts)


def test_finalize_writes_result_files(data_root: Path) -> None:
    at = run_page("pages/3_Finalize.py")
    next(b for b in at.button if b.label == "Write result files").click()
    at.run()
    assert [str(e.value) for e in at.exception] == []

    out = data_root / "results" / "02_demo_d3"
    assert (out / POSES_FILE).is_file()
    assert (out / MOLECULES_FILE).is_file()
    assert (out / METADATA_FILE).is_file()
    assert any(p.name.endswith("_relaxed.xyz") for p in (out / STRUCTURES_DIR).iterdir())


def test_unified_hub_switches_across_all_three_programs_without_collision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Unified root app.py switches across all three GUIs (and Coverage & Dimer) without module or route collision."""
    import sys
    from streamlit.testing.v1 import AppTest

    fet_dir = tmp_path / "fet_data"
    fet_dir.mkdir(parents=True, exist_ok=True)
    ads_dir = tmp_path / "ads_data"
    ads_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FET_DATA_ROOT", str(fet_dir))
    monkeypatch.setenv("ADS_DATA_ROOT", str(ads_dir))

    app_path = _REPO_ROOT / "app.py"
    mos2_main = _REPO_ROOT / "MoS2_optical_analysis" / "mos2_gui" / "Main.py"
    fet_run = _REPO_ROOT / "FET_analysis" / "fet_gui" / "Run.py"
    ads_run = _REPO_ROOT / "MoS2_adsorption_sim" / "ads_gui" / "Run.py"
    ads_cov = _REPO_ROOT / "MoS2_adsorption_sim" / "ads_gui" / "pages" / "4_Coverage_Dimer.py"

    at = AppTest.from_file(str(app_path), default_timeout=120).run()
    assert not at.exception

    # Click hub card button for MoS2 Optical Analysis
    at.button(key="hub_open_mos2").click().run()
    assert not at.exception

    # Switch cleanly to FET Analysis, Adsorption Run, and Coverage & Dimer via unified navigation
    at.switch_page(str(fet_run)).run()
    assert not at.exception
    at.switch_page(str(ads_run)).run()
    assert not at.exception
    at.switch_page(str(ads_cov)).run()
    assert not at.exception
    at.switch_page(str(mos2_main)).run()
    assert not at.exception

    assert {"mos2_gui", "fet_gui", "ads_gui"} <= set(sys.modules)
    assert "gui" not in sys.modules


def test_trash_and_restore_batch_and_molecule(tmp_path: Path, monkeypatch) -> None:
    """Soft-deleting moves data to data/bin, supports restore, and permanent delete removes it."""
    from ads_gui.state import (
        delete_trashed_item_permanently,
        list_batches,
        list_trashed_items,
        molecules_root,
        restore_trashed_item,
        results_root,
        trash_batch,
        trash_molecule_file,
    )

    data_dir = tmp_path / "ads_data"
    monkeypatch.setenv("ADS_DATA_ROOT", str(data_dir))

    batch_dir = results_root() / "batch_one"
    batch_dir.mkdir(parents=True)
    (batch_dir / "batch_state.json").write_text("{}", encoding="utf-8")

    mol_dir = molecules_root()
    mol_dir.mkdir(parents=True)
    (mol_dir / "custom.xyz").write_text("1\nH\nH 0 0 0\n", encoding="utf-8")

    assert list_batches() == ["batch_one"]
    trash_batch("batch_one")
    assert list_batches() == []
    trashed_b = list_trashed_items("results")
    assert len(trashed_b) == 1
    assert trashed_b[0]["original_name"] == "batch_one"

    restored = restore_trashed_item("results", trashed_b[0]["entry_id"])
    assert restored == "batch_one"
    assert list_batches() == ["batch_one"]

    trash_batch("batch_one")
    trashed_b2 = list_trashed_items("results")
    delete_trashed_item_permanently("results", trashed_b2[0]["entry_id"])
    assert list_trashed_items("results") == []

    trash_molecule_file("custom.xyz")
    assert not (mol_dir / "custom.xyz").exists()
    trashed_m = list_trashed_items("molecules")
    assert len(trashed_m) == 1
    restore_trashed_item("molecules", trashed_m[0]["entry_id"])
    assert (mol_dir / "custom.xyz").is_file()


def test_run_page_exposes_substrate_and_supercell(tmp_path: Path, monkeypatch) -> None:
    """Run.py exposes substrate candidates (fixed to 2H-MoS2) and supercell nx/ny in the main form."""
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("ADS_DATA_ROOT", str(tmp_path / "ads_data"))
    run_py = _REPO_ROOT / "MoS2_adsorption_sim" / "ads_gui" / "Run.py"
    at = AppTest.from_file(str(run_py), default_timeout=60).run()
    assert not at.exception
    assert at.selectbox(key="run_substrate").value == "2H-MoS2"
    assert at.number_input(key="run_nx").value == 4
    assert at.number_input(key="run_ny").value == 4


def test_gui_md_only_batch_workflow_across_all_pages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run.py launches MD-only batches and Poses/Compare/Finalize render MD trajectories cleanly."""
    from ads_core.report.export import load_batch_run

    monkeypatch.setenv("ADS_DATA_ROOT", str(tmp_path))
    at = run_page("Run.py")
    assert [str(e.value) for e in at.exception] == []

    next(c for c in at.checkbox if c.key == "run_show_advanced").set_value(True)
    next(c for c in at.checkbox if c.key == "run_md_enabled").set_value(True)
    at.run()
    assert [str(e.value) for e in at.exception] == []

    next(t for t in at.text_input if t.key == "run_batch_name").set_value("ui_md_only")
    next(m for m in at.multiselect if m.key == "run_surfaces").set_value(["pristine"])
    next(m for m in at.multiselect if m.key == "run_presets").set_value(["H2O"])
    next(n for n in at.number_input if n.key == "run_nx").set_value(2)
    next(n for n in at.number_input if n.key == "run_ny").set_value(2)
    next(m for m in at.multiselect if m.key == "run_sites").set_value(["Hollow"])
    next(m for m in at.multiselect if m.key == "run_orientations").set_value(["flat"])
    next(m for m in at.multiselect if m.key == "run_azimuths").set_value([0.0])
    next(c for c in at.checkbox if c.key == "run_md_only").set_value(True)
    next(n for n in at.number_input if n.key == "run_md_steps").set_value(10)
    at.run()

    next(b for b in at.button if b.key == "run_execute_btn").click()
    at.run()
    assert [str(e.value) for e in at.exception] == []

    out_dir = tmp_path / "results" / "ui_md_only"
    assert (out_dir / BATCH_STATE_FILE).is_file()
    assert (out_dir / MD_SUMMARY_FILE).is_file()
    assert any((out_dir / MD_CURVES_DIR).iterdir())

    loaded = load_batch_run(out_dir)
    assert len(loaded.md_results) == 1
    assert "<div" in md_3d_html(loaded.md_results[0])

    for page in ("pages/1_Poses.py", "pages/2_Compare.py", "pages/3_Finalize.py"):
        page_at = run_page(page)
        assert [str(e.value) for e in page_at.exception] == []
        assert [e.label for e in page_at.sidebar.expander] == SECTIONS[page]

    poses_at = run_page("pages/1_Poses.py")
    assert len(poses_at.get("plotly_chart")) == 1
    assert any(m.label == "Stayed adsorbed" for m in poses_at.metric)


def test_coverage_dimer_page_renders_empty_and_populated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, four_atp_xyz_path: Path
) -> None:
    """4_Coverage_Dimer.py handles both empty results and populated coverage/disulfide studies."""
    import yaml
    from ads_core.simulation.coverage import run_coverage_study
    from ads_core.report.coverage_view import analyze_disulfide_geometry, analyze_multimol_contacts, load_coverage_study
    from ads_gui.components.atoms2d import multimol_top_side_png
    from ads_gui.components.viewer3d import multimol_3d_html

    monkeypatch.setenv("ADS_DATA_ROOT", str(tmp_path))
    empty_at = run_page("pages/4_Coverage_Dimer.py")
    assert [str(e.value) for e in empty_at.exception] == []
    assert [e.label for e in empty_at.sidebar.expander] == ["1) Study"]
    assert empty_at.info

    # Build a small synthetic coverage study with N1, N2 dimer, and disulfide
    sim_root = Path(__file__).resolve().parents[1]
    raw = load_config(sim_root / "configs" / "track_a_4atp.yaml").as_dict()
    raw["study"]["base_config_path"] = str(sim_root / "config.yaml")
    raw["adsorbate"]["molecule_path"] = str(four_atp_xyz_path)
    raw["relaxation"]["max_steps"] = 6
    raw["relaxation"]["fmax_eV_per_A"] = 0.25
    raw["grid_cases"] = {"N1_monomer_flat": raw["grid_cases"]["N1_monomer_flat"]}
    raw["cluster_cases"] = {"N2_dimer_head_to_tail": raw["cluster_cases"]["N2_dimer_head_to_tail"]}
    raw["vacancy_desorption"]["source_cases"] = []
    raw["vacancy_desorption"]["sequential_pairs"] = {"N2_dimer_head_to_tail": "N1_monomer_flat"}
    study_yaml = tmp_path / "study.yaml"
    study_yaml.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    run_coverage_study(
        study_yaml,
        backend_override="synth_morse",
        device_override="cpu",
        output_dir_override=tmp_path / "results",
    )

    pop_at = run_page("pages/4_Coverage_Dimer.py")
    assert [str(e.value) for e in pop_at.exception] == []
    assert [e.label for e in pop_at.sidebar.expander] == ["1) Study"]
    figures = pop_at.get("plotly_chart")
    assert figures and all(json.loads(f.proto.spec)["layout"].get("width") is None for f in figures)
    assert _segmented(pop_at, "Coverage view").options == [
        "N=1–4 Coverage & Distances",
        "N=1–4 3D & 2D Viewer",
        "Dimer & Disulfide Formation",
    ]
    _segmented(pop_at, "Coverage view").set_value("N=1–4 3D & 2D Viewer").run()
    assert [str(e.value) for e in pop_at.exception] == []
    _segmented(pop_at, "Coverage view").set_value("Dimer & Disulfide Formation").run()
    assert [str(e.value) for e in pop_at.exception] == []

    bundle = load_coverage_study(tmp_path / "results" / raw["study"]["name"])
    n2_rel = bundle.structures["N2_dimer_head_to_tail_relaxed"]
    geo = analyze_multimol_contacts(n2_rel, bundle.slab_count, bundle.mol_count)
    assert geo.n_molecules == 2
    assert "S···S" in geo.contacts
    assert "<div" in multimol_3d_html(n2_rel, slab_count=bundle.slab_count, mol_count=bundle.mol_count, distance_lines=list(geo.contacts.values()))
    assert multimol_top_side_png(n2_rel, slab_count=bundle.slab_count, mol_count=bundle.mol_count).startswith(b"\x89PNG")

    drep = analyze_disulfide_geometry(
        bundle.structures["reference_slab_relaxed"],
        bundle.structures["disulfide_gas_relaxed"],
        bundle.structures["disulfide_adsorbed_initial"],
        bundle.structures["disulfide_adsorbed_relaxed"],
        bundle.slab_count,
    )
    assert drep.d_ss_relaxed_A is not None


