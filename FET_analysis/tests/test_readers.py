"""Readers and folder loading, on vendor files written from synthetic curves."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fet_core.io import b1500_csv, clarius_xls
from fet_core.io.loader import detect_reader, load_files, load_folder
from fet_core.model import CURVE_OUTPUT, CURVE_TRANSFER, CURVE_UNKNOWN, STANDARD_COLUMNS
from tests.conftest import clarius_data_rows, clarius_settings_rows, write_b1500_csv

B1500_NAME = "Transfer BG_NFET  [INTL#184_B3_BG ; (20) 9_16_2026 12_18_08 AM].csv"


def codes(warnings) -> list[str]:
    return [w.code for w in warnings]


# ---- B1500 CSV ---------------------------------------------------------------


def test_b1500_roundtrip(tmp_path: Path, config, curve) -> None:
    path = write_b1500_csv(tmp_path / B1500_NAME, curve)
    result = load_files([path], config)
    assert codes(result.warnings) == []
    (m,) = result.measurements
    assert list(m.data.columns) == list(STANDARD_COLUMNS)
    assert np.allclose(m.data["Vg"], curve["Vg"]) and np.allclose(m.data["Id"], curve["Id"])
    assert np.allclose(m.data["Ig"], curve["Ig"])  # signed Ibg wins over absIbg
    assert m.data["Vs"].isna().all() and m.data["time"].isna().all()
    assert (m.label, m.group, m.position) == ("INTL#184_B3_BG", "INTL#184_BG", "B3")
    assert m.curve_type == CURVE_TRANSFER
    assert m.key == (B1500_NAME, "1")
    assert m.metadata["source_columns"]["Vg"] == "Vbg"
    c = m.conditions
    assert (c["sweep_start_V"], c["sweep_stop_V"], c["dual_sweep"]) == (-40.0, 60.0, True)
    assert c["measured_at"] == "2026-09-16T00:18:08"
    assert (c["vds_V"], c["vd_source"], c["vs_source"]) == (1.0, "measured", "header")
    assert len(m.source_sha256) == 64


def test_b1500_label_falls_back_to_remarks_then_stem(tmp_path: Path, config, curve) -> None:
    with_remarks = write_b1500_csv(tmp_path / "export1.csv", curve, remarks="SMP7_C4")
    plain = write_b1500_csv(tmp_path / "export2.csv", curve.iloc[:50])
    first, second = load_files([with_remarks, plain], config).measurements
    assert (first.group, first.position) == ("SMP7", "C4")
    assert (second.label, second.position) == ("export2", None)


def test_b1500_abs_columns_used_when_signed_missing(tmp_path: Path, config, curve) -> None:
    path = write_b1500_csv(tmp_path / B1500_NAME, curve, gate_current_column="absIbg", extra_columns=False)
    (m,) = load_files([path], config).measurements
    assert m.metadata["source_columns"]["Ig"] == "absIbg"


def test_b1500_bad_cells_become_nan_in_place(tmp_path: Path, config, curve) -> None:
    path = write_b1500_csv(tmp_path / B1500_NAME, curve)
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    first_data = next(i for i, line in enumerate(lines) if line.startswith("DataValue"))
    cells = lines[first_data + 3].split(", ")
    cells[3] = "OVERFLOW"
    lines[first_data + 3] = ", ".join(cells)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    result = load_files([path], config)
    (m,) = result.measurements
    assert len(m.data) == len(curve)
    assert np.isnan(m.data["Id"].iloc[3]) and np.isfinite(m.data["Id"].iloc[4])
    assert codes(result.warnings) == ["non_numeric_cells"]


def test_b1500_without_data_or_columns_is_skipped_with_a_cause(tmp_path: Path, config, curve) -> None:
    path = write_b1500_csv(tmp_path / "a.csv", curve)
    text = path.read_text(encoding="utf-8-sig")
    no_rows = tmp_path / "no_rows.csv"
    no_rows.write_text("\n".join(l for l in text.splitlines() if not l.startswith("DataValue")), encoding="utf-8-sig")
    no_id = tmp_path / "no_id.csv"
    no_id.write_text(text.replace("DataName, Vbg, Vd, Id, Ibg, absId", "DataName, Vbg, Vd, Ix, Ibg, absIx"), encoding="utf-8-sig")
    result = load_files([no_rows, no_id], config)
    assert result.measurements == []
    assert sorted(codes(result.warnings)) == ["missing_required_column", "no_data_rows"]
    assert [f.status for f in result.files] == ["skipped", "skipped"]


# ---- Clarius XLS -------------------------------------------------------------


def test_clarius_named_sheets(tmp_path: Path, config, curve) -> None:
    sheets = {
        "#600_4_ATP_B2": clarius_data_rows(curve),
        "Calc": [],
        "Settings": clarius_settings_rows(["#600_4_ATP_B2", "#600_4_ATP_A3"], vd=1.0),
        "#600_4_ATP_A3": clarius_data_rows(curve, with_source=True),
    }
    measurements, warnings = clarius_xls.parse_workbook(sheets, tmp_path / "#600_4_ATP.xls", "f" * 64, config)
    assert codes(warnings) == []
    first, second = measurements
    assert (first.run_id, first.group, first.position) == ("#600_4_ATP_B2", "#600_4_ATP", "B2")
    assert second.position == "A3"
    assert np.allclose(first.data["Id"], curve["Id"]) and np.allclose(first.data["Vg"], curve["Vg"])
    assert first.data["Vs"].isna().all() and (second.data["Vs"] == 0.0).all()
    assert first.curve_type == CURVE_TRANSFER
    c = first.conditions
    assert (c["sweep_start_V"], c["sweep_stop_V"], c["sweep_step_V"], c["dual_sweep"]) == (-40.0, 60.0, 1.0, True)
    assert (c["vds_V"], c["vs_source"]) == (1.0, "header")
    assert second.conditions["vs_source"] == "measured"
    assert c["measured_at"] == "2026-08-13T21:55:13"


def test_clarius_unnamed_runs_take_the_group_from_the_file(tmp_path: Path, config, curve) -> None:
    sheets = {"Run2711": clarius_data_rows(curve), "Settings": clarius_settings_rows(["Run2711"])}
    (m,), warnings = clarius_xls.parse_workbook(sheets, tmp_path / "#89_pristine.xls", "f" * 64, config)
    assert (m.run_id, m.label, m.group, m.position) == ("Run2711", "#89_pristine", "#89_pristine", None)
    assert m.metadata["label_from"] == "file_name"
    assert codes(warnings) == []


def test_clarius_missing_settings_is_reported_not_fatal(tmp_path: Path, config, curve) -> None:
    sheets = {"S1_B2": clarius_data_rows(curve), "Settings": clarius_settings_rows(["other"])}
    (m,), warnings = clarius_xls.parse_workbook(sheets, tmp_path / "b.xls", "f" * 64, config)
    assert codes(warnings) == ["settings_block_missing"]
    assert m.conditions["sweep_start_V"] is None
    assert (m.conditions["vds_V"], m.conditions["vs_source"]) == (1.0, "assumed_zero")
    (_,), warnings = clarius_xls.parse_workbook({"S1_B2": clarius_data_rows(curve)}, tmp_path / "b.xls", "f" * 64, config)
    assert codes(warnings) == ["settings_sheet_missing"]


def test_clarius_sheet_without_required_columns_is_skipped(tmp_path: Path, config, curve) -> None:
    sheets = {"notes": [["comment", "value"], ["a", 1]], "S1_B2": clarius_data_rows(curve)}
    measurements, warnings = clarius_xls.parse_workbook(sheets, tmp_path / "b.xls", "f" * 64, config)
    assert [m.run_id for m in measurements] == ["S1_B2"]
    assert sorted(codes(warnings)) == ["missing_required_column", "settings_sheet_missing"]


# ---- curve type, detection, folder loading -----------------------------------


def test_output_and_unknown_curves_are_classified(tmp_path: Path, config, curve) -> None:
    vd = np.tile(np.linspace(0.0, 5.0, 51), 3)
    vg = np.repeat([0.0, 10.0, 20.0], 51)
    output = pd.DataFrame({"Vg": vg, "Vd": vd, "Vs": np.nan, "Id": vd * 1e-6, "Ig": 1e-12, "Is": np.nan, "time": np.nan})
    constant = output.assign(Vd=1.0, Vg=0.0)
    sheets = {"out_A1": clarius_data_rows(output), "const_A2": clarius_data_rows(constant)}
    measurements, warnings = clarius_xls.parse_workbook(sheets, tmp_path / "b.xls", "f" * 64, config)
    assert [m.curve_type for m in measurements] == [CURVE_OUTPUT, CURVE_UNKNOWN]
    assert "unknown_curve_type" in codes(warnings)


def test_folder_loading_skips_unknown_and_duplicate_files(tmp_path: Path, config, curve) -> None:
    original = write_b1500_csv(tmp_path / B1500_NAME, curve)
    copy = tmp_path / (original.stem + "-1.csv")
    copy.write_bytes(original.read_bytes())
    (tmp_path / "notes.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (tmp_path / "readme.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    write_b1500_csv(tmp_path / "sub" / "inner.csv", curve)

    result = load_folder(tmp_path, config)
    assert len(result.measurements) == 1
    by_name = {f.path.name: f for f in result.files}
    assert by_name[original.name].status == "read" and by_name[original.name].measurement_count == 1
    assert by_name[copy.name].reason == f"same content as {original.name}"
    assert by_name["notes.csv"].reader is None and by_name["readme.txt"].reader is None
    assert "inner.csv" not in by_name
    assert codes(result.warnings) == ["duplicate_file"]
    assert detect_reader(tmp_path / "notes.csv", config) is None
    assert detect_reader(original, config) is b1500_csv


def test_load_folder_requires_a_folder(tmp_path: Path, config) -> None:
    with pytest.raises(NotADirectoryError):
        load_folder(tmp_path / "missing", config)


# ---- real instrument files (local only) --------------------------------------


def _real_data_dirs() -> list[Path]:
    root = Path(os.environ.get("FET_REAL_DATA_DIR", Path(__file__).resolve().parents[1] / "data" / "raw"))
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and any(f.suffix.lower() in {".csv", ".xls"} for f in p.iterdir()))


@pytest.mark.parametrize("folder", _real_data_dirs(), ids=lambda p: p.name)
def test_real_folders_load_completely(folder: Path, config) -> None:
    """Every instrument file in a local batch folder becomes at least one transfer measurement."""
    result = load_folder(folder, config)
    instrument_files = [f for f in result.files if f.path.suffix.lower() in {".csv", ".xls"}]
    assert instrument_files and all(f.status == "read" for f in instrument_files), [
        (f.path.name, f.reason) for f in instrument_files if f.status != "read"
    ]
    assert all(m.curve_type == CURVE_TRANSFER for m in result.measurements)
    assert all(m.data["Vg"].notna().all() and m.data["Id"].notna().all() for m in result.measurements)
    assert [w for w in result.warnings if w.severity == "error"] == []
