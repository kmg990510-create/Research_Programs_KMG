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
