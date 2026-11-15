from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest
from ase.units import kB

from ads_core.cli import main as cli_main
from ads_core.config import load_config
from ads_core.model import ORIENTATION_ANCHOR_DOWN, ORIENTATION_FLAT, SITE_HOLLOW, SITE_S_TOP, SITE_VS
from ads_core.pipeline import ordered_groups, poses_frame, run_batch
from ads_core.report.export import (
    BATCH_STATE_FILE,
    BINDING_CURVES_DIR,
    METADATA_FILE,
    MOLECULES_FILE,
    POSES_FILE,
    RELAX_CURVES_DIR,
    STRUCTURES_DIR,
    WARNINGS_FILE,
    export_run,
    load_batch_run,
)
from ads_core.report.summary import boltzmann_weights, molecule_summary
from ads_core.review import DECISION_APPROVED, DECISION_AUTO, DECISION_REJECTED, ReviewState, load_review, make_group_key, save_review


def test_boltzmann_weights_and_summary_math() -> None:
    energies = [-0.20, -0.15, -0.10]
    temp = 300.0
    w = boltzmann_weights(energies, temp)
    assert pytest.approx(float(w.sum()), abs=1e-12) == 1.0
    # Check ratio w[1] / w[0] == exp(-(0.05) / (kB * 300))
    expected_ratio = math.exp(-0.05 / (float(kB) * temp))
    assert w[1] / w[0] == pytest.approx(expected_ratio, rel=1e-9)

    df = pd.DataFrame(
        [
            {
                "pose_id": "p1",
                "surface_id": "pristine_4x4",
                "defect_type": "pristine",
                "molecule_id": "H2O",
                "site_type": "Hollow",
                "calculator_id": "synth_morse+d3",
                "group_display": "Pristine H2O",
                "included": True,
                "e_ads_eV": -0.20,
                "e_ads_umlip_eV": 0.02,
                "e_ads_d3_eV": -0.22,
                "vdw_fraction": 1.10,
                "e_int_eV": -0.21,
                "e_def_slab_eV": 0.005,
                "e_def_mol_eV": 0.005,
                "d_min_A": 3.1,
                "dz_com_A": 3.2,
            },
            {
                "pose_id": "p2",
                "surface_id": "pristine_4x4",
                "defect_type": "pristine",
                "molecule_id": "H2O",
                "site_type": "S_top",
                "calculator_id": "synth_morse+d3",
                "group_display": "Pristine H2O",
                "included": True,
                "e_ads_eV": -0.15,
                "e_ads_umlip_eV": 0.03,
                "e_ads_d3_eV": -0.18,
                "vdw_fraction": 1.20,
                "e_int_eV": -0.16,
                "e_def_slab_eV": 0.005,
                "e_def_mol_eV": 0.005,
                "d_min_A": 3.3,
                "dz_com_A": 3.4,
            },
            {
                "pose_id": "p3_rejected",
                "surface_id": "pristine_4x4",
                "defect_type": "pristine",
                "molecule_id": "H2O",
                "site_type": "Bridge",
                "calculator_id": "synth_morse+d3",
                "group_display": "Pristine H2O",
                "included": False,
                "e_ads_eV": -0.99,  # rejected must be excluded from summary!
                "e_ads_umlip_eV": -0.90,
                "e_ads_d3_eV": -0.09,
                "vdw_fraction": 0.09,
                "e_int_eV": -0.99,
                "e_def_slab_eV": 0.0,
                "e_def_mol_eV": 0.0,
                "d_min_A": 2.0,
                "dz_com_A": 2.1,
            },
        ]
    )
    summary = molecule_summary(df, temp_K=300.0)
    assert len(summary) == 1
    row = summary.iloc[0]
    assert row["n_poses"] == 3
    assert row["n_included"] == 2
    assert row["best_pose_id"] == "p1"
    assert row["best_site"] == "Hollow"
    assert row["e_ads_min_eV"] == pytest.approx(-0.20)
    assert row["e_ads_corrugation_eV"] == pytest.approx(0.05)
    w2 = boltzmann_weights([-0.20, -0.15], 300.0)
    assert row["e_ads_boltzmann_eV"] == pytest.approx(float(w2[0] * (-0.20) + w2[1] * (-0.15)))


def test_run_batch_review_export_and_reload(tmp_path: Path) -> None:
    config = load_config()
    progress_calls: list[tuple[int, int, str]] = []

    run = run_batch(
        "test_screening",
        config,
        surfaces=["pristine_2x2", "V_S_2x2"],
        molecules=["H2O"],
        backend="synth_morse",
        d3_enabled=True,
        site_types=[SITE_HOLLOW, SITE_S_TOP, SITE_VS],
        orientations=[ORIENTATION_FLAT, ORIENTATION_ANCHOR_DOWN],
        azimuth_angles_deg=[0.0],
        scan_binding_curves=True,
        progress_callback=lambda cur, tot, pid: progress_calls.append((cur, tot, pid)),
    )

    # pristine: 2 sites (Hollow, S_top) x 2 ori = 4; V_S: 3 sites (V_S, Hollow, S_top) x 2 ori = 6 -> 10 poses
    assert len(run.results) == 10
    assert len(progress_calls) == 10
    assert progress_calls[-1][0] == 10 and progress_calls[-1][1] == 10
    assert len(run.binding_curves) == 2

    # Apply human review (approve 1, reject 1, rename & order groups)
    review = ReviewState()
    first_id = run.results[0].pose_id
    second_id = run.results[1].pose_id
    review.set_decision(first_id, DECISION_APPROVED, note="Good physisorption site")
    review.set_decision(second_id, DECISION_REJECTED, note="Exclude duplicate orientation")
    gk_vs = make_group_key("V_S_2x2", "H2O", "synth_morse+d3")
    gk_pr = make_group_key("pristine_2x2", "H2O", "synth_morse+d3")
    review.group_names[gk_vs] = "S-Vacancy (H2O)"
    review.group_names[gk_pr] = "Pristine (H2O)"
    review.group_order = ["S-Vacancy (H2O)", "Pristine (H2O)"]

    review_path = tmp_path / "out" / "review.json"
    save_review(review_path, review)
    reloaded_review = load_review(review_path)
    assert reloaded_review.decision(first_id) == DECISION_APPROVED
    assert reloaded_review.decision(second_id) == DECISION_REJECTED
    assert reloaded_review.note(first_id) == "Good physisorption site"

    # Verify reset to auto
    reloaded_review.set_decision(first_id, DECISION_AUTO, note="")
    assert reloaded_review.decision(first_id) == DECISION_AUTO
    assert reloaded_review.note(first_id) == ""
    reloaded_review.set_decision(first_id, DECISION_APPROVED, note="Good physisorption site")

    out_dir = tmp_path / "out"
    export_run(run, reloaded_review, out_dir)

    assert (out_dir / POSES_FILE).is_file()
    assert (out_dir / MOLECULES_FILE).is_file()
    assert (out_dir / WARNINGS_FILE).is_file()
    assert (out_dir / METADATA_FILE).is_file()
    assert (out_dir / BATCH_STATE_FILE).is_file()
    assert len(list((out_dir / RELAX_CURVES_DIR).glob("*.csv"))) == 10
    assert len(list((out_dir / BINDING_CURVES_DIR).glob("*.csv"))) == 2
    assert len(list((out_dir / STRUCTURES_DIR).glob("*_relaxed.xyz"))) == 10

    poses_csv = pd.read_csv(out_dir / POSES_FILE, encoding="utf-8-sig")
    assert len(poses_csv) == 10
    rejected_row = poses_csv[poses_csv["pose_id"] == second_id].iloc[0]
    assert not bool(rejected_row["included"])

    mol_csv = pd.read_csv(out_dir / MOLECULES_FILE, encoding="utf-8-sig")
    assert list(mol_csv["group_display"]) == ["S-Vacancy (H2O)", "Pristine (H2O)"]
    # Pristine had 4 poses, 1 rejected -> n_poses=4, n_included=3
    pristine_row = mol_csv[mol_csv["group_display"] == "Pristine (H2O)"].iloc[0]
    assert pristine_row["n_poses"] == 4
    assert pristine_row["n_included"] == 3
    # V_S chemisorption energy is significantly stronger than pristine physisorption
    vs_row = mol_csv[mol_csv["group_display"] == "S-Vacancy (H2O)"].iloc[0]
    assert vs_row["e_ads_min_eV"] < pristine_row["e_ads_min_eV"]

    meta = json.loads((out_dir / METADATA_FILE).read_text(encoding="utf-8"))
    assert meta["program"] == "MoS2_adsorption_sim"
    assert meta["counts"]["poses"] == 10
    assert meta["counts"]["included_in_statistics"] == 9
    assert meta["calculator"]["backend"] == "synth_morse"

    # Reload BatchRun from disk and confirm tables/artifacts match without re-running
    restored = load_batch_run(out_dir)
    assert restored.name == run.name
    assert len(restored.results) == 10
    assert len(restored.binding_curves) == 2
    assert len(restored.artifacts[first_id].trajectory_frames) >= 2
    restored_frame = poses_frame(restored, reloaded_review)
    assert ordered_groups(restored_frame, reloaded_review) == ["S-Vacancy (H2O)", "Pristine (H2O)"]


def test_cli_run_and_reexport(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out_dir = tmp_path / "cli_batch"
    rc = cli_main(
        [
            "run",
            "--batch",
            "cli_batch",
            "--surfaces",
            "pristine_2x2",
            "--molecules",
            "H2O",
            "--backend",
            "synth_morse",
            "--sites",
            "Hollow",
            "--orientations",
            "flat",
            "--output-dir",
            str(out_dir),
            "--quiet",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr().out
    assert "Batch: cli_batch" in captured
    assert (out_dir / POSES_FILE).is_file()

    rc2 = cli_main(["export", "--batch-dir", str(out_dir), "--quiet"])
    assert rc2 == 0
    assert "Re-exported" in capsys.readouterr().out
