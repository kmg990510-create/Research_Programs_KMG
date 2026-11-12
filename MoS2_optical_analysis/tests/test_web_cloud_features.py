"""Tests for web/cloud deployment features (upload staging, cross-OS paths, web manual refit)."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from fitting.mos2_core.review.refit_api import ManualRefitRequest, SingleSpectrumRefitAPI
from gui.components.manual_refit_contract import build_editor_request, extract_peak_rows_from_row
from gui.components.report_loader import save_uploaded_report_files, stage_uploaded_raw_files
from gui.components.spectrum_viewer import resolve_source_file
from gui.desktop_editor.controller import ManualEditorController
from gui.desktop_editor.models import EditorRequest


class _FakeUpload:
    def __init__(self, name: str, data: bytes) -> None:
        self.name = name
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


def test_resolve_source_file_normalizes_windows_backslashes_and_foreign_roots(tmp_path: Path) -> None:
    raw_file = tmp_path / "data" / "raw" / "raman" / "sample_A" / "Y1-X1.txt"
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_text("XYDATA=\n380,100\n", encoding="utf-8")

    # Relative path with Windows backslashes
    resolved_rel = resolve_source_file(r"data\raw\raman\sample_A\Y1-X1.txt", tmp_path)
    assert resolved_rel == raw_file

    # Foreign machine absolute path containing data/raw/...
    foreign_abs = r"C:\Users\other_user\Desktop\MoS2_optical_analysis\data\raw\raman\sample_A\Y1-X1.txt"
    resolved_foreign = resolve_source_file(foreign_abs, tmp_path)
    assert resolved_foreign == raw_file


def test_stage_uploaded_raw_files_handles_txt_zip_and_mapping_csv(tmp_path: Path) -> None:
    raw_root = tmp_path / "data" / "raw" / "raman"

    # 1) Direct TXT + ZIP upload
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("sub/Y1-X2.txt", "XYDATA=\n380,120\n")
        zf.writestr("__MACOSX/._Y1-X2.txt", "junk")
        zf.writestr("../evil.txt", "blocked")

    uploads = [
        _FakeUpload("Y1-X1.txt", b"XYDATA=\n380,100\n"),
        _FakeUpload("batch.zip", zip_buf.getvalue()),
    ]
    res = stage_uploaded_raw_files(
        uploads,
        modality="raman",
        folder_name="my sample 01",
        base_raw_dir=raw_root,
    )
    target_dir = res["target_dir"]
    assert target_dir == (raw_root / "my_sample_01").resolve()
    assert (target_dir / "Y1-X1.txt").exists()
    assert (target_dir / "sub" / "Y1-X2.txt").exists()
    assert not (target_dir / "__MACOSX").exists()

    # 2) Mapping CSV auto-split
    mapping_csv = (
        "FILETYPE=RAMAN SPECTRUM (MAPPING)\n"
        "LASER=532nm\n"
        "XAREA=Min:0, Max:1, Step:1, Count:2\n"
        "YAREA=Min:0, Max:0, Step:1, Count:1\n"
        "X,Y,Z,XINDEX,YINDEX,ZINDEX,380.0,400.0\n"
        "0.0,0.0,0.0,0,0,0,100,200\n"
        "1.0,0.0,0.0,1,0,0,110,210\n"
    ).encode("utf-8")
    res_map = stage_uploaded_raw_files(
        [_FakeUpload("map_scan.CSV", mapping_csv)],
        modality="raman",
        folder_name="map_test",
        base_raw_dir=raw_root,
        split_raman_mapping=True,
    )
    map_dir = res_map["target_dir"]
    assert (map_dir / "Y01-X01.txt").exists()
    assert (map_dir / "Y01-X02.txt").exists()
    assert len(res_map["split_summaries"]) == 1


def test_save_uploaded_report_files_routes_by_modality_and_type(tmp_path: Path) -> None:
    pl_report_bytes = json.dumps(
        {"run_id": "pl_test", "modality": "pl", "spectra": [{"spectrum_id": "s1", "pl_position": 1.85}]}
    ).encode("utf-8")
    raman_override_bytes = json.dumps({"run_id": "raman_test", "overrides": {}}).encode("utf-8")

    saved = save_uploaded_report_files(
        [
            _FakeUpload("sample_fit_report.json", pl_report_bytes),
            _FakeUpload("raman_test_manual_overrides.json", raman_override_bytes),
        ],
        default_modality="raman",
        base_results_dir=tmp_path,
    )
    assert (tmp_path / "pl" / "reports" / "sample_fit_report.json") in saved
    assert (tmp_path / "raman" / "manual_refits" / "raman_test_manual_overrides.json") in saved


def test_web_manual_refit_controller_and_api_roundtrip(tmp_path: Path) -> None:
    workspace_root = Path(__file__).resolve().parents[1]
    x = [float(370 + i * 0.5) for i in range(100)]
    import numpy as np

    x_arr = np.asarray(x, dtype=float)
    y_arr = (
        50.0
        + 120.0 * np.exp(-0.5 * ((x_arr - 384.0) / 1.5) ** 2)
        + 180.0 * np.exp(-0.5 * ((x_arr - 404.0) / 1.6) ** 2)
    )
    row_snapshot = {
        "spectrum_id": "Y1-X1",
        "modality": "raman",
        "selected_model": "peak_2_model",
        "line_profile": "pvoigt",
        "bg_slope": 0.0,
        "bg_intercept": 50.0,
        "e2g_position": 384.0,
        "e2g_height": 120.0,
        "e2g_fwhm": 3.2,
        "e2g_fraction": 0.5,
        "a1g_position": 404.0,
        "a1g_height": 180.0,
        "a1g_fwhm": 3.4,
        "a1g_fraction": 0.5,
    }
    peaks = extract_peak_rows_from_row(row_snapshot)
    assert [p["peak"] for p in peaks] == ["e2g", "a1g"]

    req_payload = build_editor_request(
        report_path=tmp_path / "dummy_fit_report.json",
        spectrum_id="Y1-X1",
        modality="raman",
        source_file="",
        selected_model="peak_2_model",
        calibration_offset=0.0,
        row_snapshot=row_snapshot,
        x=x,
        y=y_arr.tolist(),
    )
    ctrl = ManualEditorController(EditorRequest.from_payload(req_payload))
    metrics = ctrl.preview_metrics()
    assert metrics.rmse is not None and metrics.rmse > 0.0

    api = SingleSpectrumRefitAPI(project_root=workspace_root)
    res_manual = api.submit_refit(ManualRefitRequest.from_payload(req_payload))
    assert res_manual["status"] == "ok"
    assert len(res_manual["fitted_y"]) == len(x)


def test_is_cloud_runtime_honors_env_override(monkeypatch) -> None:
    from fitting.mos2_core.core.runtime_paths import is_cloud_runtime

    monkeypatch.setenv("MOS2_CLOUD_MODE", "1")
    assert is_cloud_runtime() is True
    monkeypatch.setenv("MOS2_CLOUD_MODE", "0")
    assert is_cloud_runtime() is False


def test_standalone_report_embeds_raw_xy_only_in_json_and_merges_overrides_on_export(
    tmp_path: Path,
) -> None:
    import pandas as pd
    from fitting.mos2_core.core.default_stages import build_default_context, build_default_stages
    from fitting.mos2_core.core.pipeline import run_pipeline
    from fitting.mos2_core.io import generate_dummy_spectra
    from fitting.mos2_core.review.manual_overrides import upsert_manual_override
    from gui.components.parameter_editor import apply_table_edits_to_report
    from gui.components.report_loader import (
        build_projected_csv_bytes,
        build_projected_report_json_bytes,
        load_report_payload,
        load_spectra_dataframe,
    )

    workspace_root = Path(__file__).resolve().parents[1]
    config_dir = workspace_root / "fitting" / "mos2_raman" / "config"
    raw_spectra = generate_dummy_spectra(count=2)
    ctx = build_default_context(
        run_id="standalone_test",
        artifact_dir=tmp_path,
        config_dir=config_dir,
    )
    stages = build_default_stages(config=ctx.config)
    result = run_pipeline(raw_spectra=raw_spectra, stages=stages, context=ctx)
    assert result.reports
    report_json = Path(result.reports[0].path)
    report_csv = Path(result.reports[1].path)
    assert report_json.exists()
    assert report_csv.exists()

    raw_payload = json.loads(report_json.read_text(encoding="utf-8"))
    first_row = raw_payload["spectra"][0]
    assert isinstance(first_row.get("raw_x"), list) and len(first_row["raw_x"]) > 10
    assert isinstance(first_row.get("raw_y"), list) and len(first_row["raw_y"]) == len(first_row["raw_x"])

    csv_df = pd.read_csv(report_csv)
    assert "raw_x" not in csv_df.columns
    assert "raw_y" not in csv_df.columns

    # Apply manual override + Flagged Spectra table edit
    spec_id = str(first_row["spectrum_id"])
    upsert_manual_override(
        report_json=report_json,
        spectrum_id=spec_id,
        action_type="model_override",
        selected_model="peak_3_model",
        params={"e2g_position": 385.123},
        metrics={"rmse": 0.42},
        fitted_y=[1.0, 2.0, 3.0],
        operator_note="model_switch",
    )
    orig_df = load_spectra_dataframe(str(report_json))
    edited_df = orig_df.copy()
    edited_df.loc[edited_df["spectrum_id"] == spec_id, "review_decision"] = "accepted"
    edited_df.loc[edited_df["spectrum_id"] == spec_id, "a1g_position"] = 405.678
    count = apply_table_edits_to_report(
        original=orig_df,
        edited=edited_df,
        report_path=report_json,
    )
    assert count == 1

    # Merged JSON export should preserve both model_override (e2g_position) and review_decision/a1g_position
    projected_payload = load_report_payload(str(report_json), cache_bust_mtime_ns=1, manual_overrides_mtime_ns=2)
    merged_json = json.loads(build_projected_report_json_bytes(projected_payload).decode("utf-8"))
    merged_row = next(r for r in merged_json["spectra"] if r["spectrum_id"] == spec_id)
    assert merged_row["selected_model"] == "peak_3_model"
    assert merged_row["e2g_position"] == 385.123
    assert merged_row["a1g_position"] == 405.678
    assert merged_row["review_decision"] == "accepted"
    assert merged_row["reviewed"] is True

    # Merged CSV export should exclude raw_x/raw_y and include updated values
    merged_csv_df = pd.read_csv(io.BytesIO(build_projected_csv_bytes(projected_payload, report_csv)))
    assert "raw_x" not in merged_csv_df.columns
    assert "raw_y" not in merged_csv_df.columns
    csv_row = merged_csv_df.loc[merged_csv_df["spectrum_id"] == spec_id].iloc[0]
    assert csv_row["selected_model"] == "peak_3_model"
    assert float(csv_row["e2g_position"]) == 385.123
    assert float(csv_row["a1g_position"]) == 405.678
    assert csv_row["review_decision"] == "accepted"

