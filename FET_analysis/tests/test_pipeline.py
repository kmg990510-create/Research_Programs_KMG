"""Batch run, review state, result files and the command line."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from fet_core.cli import main
from fet_core.pipeline import ordered_groups, results_frame, run_folder, status_counts
from fet_core.report.export import (
    CURVES_DIR,
    GROUPS_FILE,
    MEASUREMENTS_FILE,
    METADATA_FILE,
    RESULTS_FILE,
    WARNINGS_FILE,
    export_run,
)
from fet_core.report.summary import METRICS, group_summary, metric_label
from fet_core.review import ReviewState, load_review, run_key, save_review
from fet_core.synth import transfer_curve
from tests.conftest import write_b1500_csv


def file_name(group: str, position: str) -> str:
    return f"Transfer BG_NFET  [{group}_{position}_BG ; (1) 9_16_2026 12_18_08 AM].csv"


@pytest.fixture
def batch(tmp_path: Path, device) -> Path:
    """Two groups: SMP#1 (A1, B2) and SMP#2 (C3, and a dead device D4)."""
    folder = tmp_path / "raw" / "batch_a"
    folder.mkdir(parents=True)
    devices = {
        ("SMP#1", "A1"): device,
        ("SMP#1", "B2"): replace(device, vth_V=7.0, mobility_cm2_per_Vs=30.0),
        ("SMP#2", "C3"): replace(device, vth_V=-2.0, mobility_cm2_per_Vs=10.0, hysteresis_V=2.0),
    }
    for (group, position), dev in devices.items():
        write_b1500_csv(folder / file_name(group, position), transfer_curve(dev, -40.0, 60.0, 0.5))
    dead = transfer_curve(device, -40.0, 60.0, 0.5)
    dead["Id"] = 2e-12
    write_b1500_csv(folder / file_name("SMP#2", "D4"), dead)
    (folder / "notes.txt").write_text("not a measurement", encoding="utf-8")
    return folder


def test_run_folder_and_results_frame(batch: Path, config) -> None:
    run = run_folder(batch, config)
    frame = results_frame(run)
    assert run.name == "batch_a"
    assert len(run.loaded.measurements) == 4 and len(frame) == 8
    assert status_counts(frame) == {"valid": 6, "attention": 0, "invalid": 2}
    assert set(frame["group_display"]) == {"SMP#1_BG", "SMP#2_BG"}
    assert frame["decision"].eq("auto").all()
    assert frame["included"].sum() == 6 and not frame.loc[frame["status"] == "invalid", "included"].any()
    row = frame[(frame["position"] == "B2") & (frame["sweep"] == "forward")].iloc[0]
    assert row["mobility_cm2_per_Vs"] == pytest.approx(30.0, rel=0.02)
    assert row["i_on_uA_per_um"] == pytest.approx(row["i_on_A"] * 1e6 / 10.0)
    assert (row["W_um"], row["L_um"], row["t_ox_nm"], row["eps_r"]) == (10.0, 5.0, 300.0, 3.9)
    assert run.measurement(file_name("SMP#1", "A1"), "1").position == "A1"


def test_review_changes_analysis_inputs_and_statistics(batch: Path, config) -> None:
    review = ReviewState(
        geometry={"W_um": 20.0, "L_um": 5.0, "t_ox_nm": 300.0, "eps_r": 3.9},
        vth_subtract_half_vds=True,
        vth_const_current_nA_per_um=10.0,
        geometry_overrides={run_key(file_name("SMP#1", "B2"), "1"): {"W_um": 40.0, "L_um": 5.0, "t_ox_nm": 300.0, "eps_r": 3.9}},
        group_names={"SMP#1_BG": "Pristine", "SMP#2_BG": "Treated"},
        group_order=["Treated", "Pristine"],
    )
    review.set_decision(file_name("SMP#1", "A1"), "1", "backward", "rejected", "scratched")
    review.set_decision(file_name("SMP#2", "C3"), "1", "forward", "approved")
    run = run_folder(batch, config, review)
    frame = results_frame(run, review)

    a1 = frame[(frame["position"] == "A1") & (frame["sweep"] == "forward")].iloc[0]
    b2 = frame[(frame["position"] == "B2") & (frame["sweep"] == "forward")].iloc[0]
    assert a1["mobility_cm2_per_Vs"] == pytest.approx(10.0, rel=0.02)  # W doubled
    assert b2["mobility_cm2_per_Vs"] == pytest.approx(7.5, rel=0.02)  # W x4 for this device only
    assert (a1["W_um"], b2["W_um"]) == (20.0, 40.0)
    assert a1["vth_linear_method"].endswith("minus_half_vds")
    assert a1["vth_const_current_level_A"] == pytest.approx(10e-9 * 20.0)

    rejected = frame[(frame["position"] == "A1") & (frame["sweep"] == "backward")].iloc[0]
    assert (rejected["decision"], rejected["note"], bool(rejected["included"])) == ("rejected", "scratched", False)
    assert ordered_groups(frame, review) == ["Treated", "Pristine"]

    summary = group_summary(frame, ordered_groups(frame, review))
    assert list(summary["group"]) == ["Treated", "Treated", "Pristine", "Pristine"]
    pristine_back = summary[(summary["group"] == "Pristine") & (summary["sweep"] == "backward")].iloc[0]
    assert (pristine_back["n_sweeps"], pristine_back["n_included"]) == (2, 1)
    assert pd.isna(pristine_back["mobility_cm2_per_Vs_std"])  # one value: no spread
    treated_fwd = summary[(summary["group"] == "Treated") & (summary["sweep"] == "forward")].iloc[0]
    assert (treated_fwd["n_sweeps"], treated_fwd["n_included"]) == (2, 1)  # the dead device is not counted
    assert treated_fwd["hysteresis_vth_linear_V_median"] == pytest.approx(2.0, abs=0.05)

    review.set_decision(file_name("SMP#1", "A1"), "1", "backward", "auto", "")
    assert review.decisions == {f"{file_name('SMP#2', 'C3')}|1|forward": "approved"} and review.notes == {}
    with pytest.raises(ValueError):
        review.set_decision("x", "1", "forward", "maybe")


def test_review_file_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "results" / "batch_a" / "review.json"
    assert load_review(path) == ReviewState()
    review = ReviewState(geometry={"W_um": 3.0, "L_um": 3.0, "t_ox_nm": 90.0, "eps_r": 3.9}, group_names={"a": "가"})
    review.set_decision("f.csv", "1", "forward", "rejected", "메모")
    save_review(path, review)
    assert load_review(path) == review
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == "fet_review.v1"


def test_export_writes_tables_and_metadata(batch: Path, config, tmp_path: Path) -> None:
    review = ReviewState(group_names={"SMP#1_BG": "Pristine"})
    review.set_decision(file_name("SMP#1", "B2"), "1", "forward", "rejected")
    run = run_folder(batch, config, review)
    out = tmp_path / "results" / "batch_a"
    (out / CURVES_DIR).mkdir(parents=True)
    (out / CURVES_DIR / "old_group_forward.csv").write_text("stale", encoding="utf-8")
    files = export_run(run, review, out)

    names = {p.relative_to(out).as_posix() for p in files}
    assert {RESULTS_FILE, GROUPS_FILE, WARNINGS_FILE, MEASUREMENTS_FILE, METADATA_FILE} <= names
    assert {f"{CURVES_DIR}/Pristine_forward.csv", f"{CURVES_DIR}/Pristine_backward.csv", f"{CURVES_DIR}/SMP#2_BG_forward.csv"} <= names
    assert not (out / CURVES_DIR / "old_group_forward.csv").exists()

    results = pd.read_csv(out / RESULTS_FILE)
    assert len(results) == 8 and {"vth_linear_V", "decision", "included", "group_display"} <= set(results.columns)
    forward = pd.read_csv(out / CURVES_DIR / "Pristine_forward.csv")
    assert list(forward.columns) == ["Vg (V)", "SMP#1_A1_BG [1] Id (A)"]  # B2 forward was rejected
    assert len(forward) == 201 and forward["Vg (V)"].is_monotonic_increasing
    backward = pd.read_csv(out / CURVES_DIR / "Pristine_backward.csv")
    assert backward.shape[1] == 3
    measurements = pd.read_csv(out / MEASUREMENTS_FILE)
    assert len(measurements) == 4 * 401 and measurements["point"].max() == 400
    warnings = pd.read_csv(out / WARNINGS_FILE)
    assert set(warnings["code"]) == {"no_gate_modulation"}

    meta = json.loads((out / METADATA_FILE).read_text(encoding="utf-8"))
    assert meta["counts"] == {"measurements": 4, "sweeps": 8, "included_in_statistics": 5, "status": {"valid": 6, "attention": 0, "invalid": 2}}
    by_name = {f["name"]: f for f in meta["input_files"]}
    assert by_name["notes.txt"]["status"] == "skipped" and len(by_name[file_name("SMP#1", "A1")]["sha256"]) == 64
    assert meta["config"]["device"]["W_um"] == 10.0 and meta["analysis_settings"]["gm_method"] == "lagged_median_slope"
    assert meta["review"]["decisions"] and meta["version"]


def test_metric_labels() -> None:
    assert metric_label("mobility_cm2_per_Vs") == "Mobility (cm²/Vs)"
    assert metric_label("on_off_decades") == "log10(on/off)"
    assert all(len(pair) == 2 for pair in METRICS.values())


def test_cli(batch: Path, tmp_path: Path, capsys) -> None:
    out = tmp_path / "out"
    assert main(["--input-dir", str(batch), "--output-dir", str(out), "--quiet"]) == 0
    printed = capsys.readouterr().out
    assert "Measurements: 4" in printed and (out / RESULTS_FILE).exists()
    assert main(["--input-dir", str(tmp_path / "nowhere")]) == 2
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["--input-dir", str(empty), "--output-dir", str(tmp_path / "out2"), "--quiet"]) == 1
