from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from fitting.mos2_core.core import runtime_paths
from fitting.mos2_core.core.default_stages import build_default_context, build_default_stages
from fitting.mos2_core.core.pipeline import run_pipeline
from fitting.mos2_core.io import generate_dummy_spectra, load_pipeline_config

WORKSPACE = Path(__file__).resolve().parents[1]
RAMAN_CONFIG_DIR = WORKSPACE / "fitting" / "mos2_raman" / "config"
THRESHOLDS = WORKSPACE / "thresholds.yaml"


def _write_thresholds(path: Path, edit) -> Path:
    payload = yaml.safe_load(THRESHOLDS.read_text(encoding="utf-8"))
    edit(payload)
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def test_workspace_thresholds_are_merged_into_sections() -> None:
    assert runtime_paths.thresholds_path() == THRESHOLDS
    config = load_pipeline_config(RAMAN_CONFIG_DIR)

    prefit = config["raman"]["fit"]["prefit"]
    # threshold keys come from thresholds.yaml, window keys stay in raman.yaml
    assert prefit["e2g_snr_hard_min"] == 2.0
    assert prefit["noise_windows"]["left"] == [350.0, 360.0]
    assert config["raman"]["post_selection_qc"]["delta_outlier"]["absolute_range"]["min"] == 15.0
    assert config["raman"]["si_calibration"]["target_peak"] == 520.0
    assert config["review"]["confidence_threshold"] == 0.8
    assert config["raman_graph"]["flagged_spectra"]["legacy_thresholds"]["delta_max"] == 25.0


def test_edited_threshold_overrides_and_bad_files_fail_loudly(tmp_path: Path) -> None:
    def _edit(payload: dict) -> None:
        payload["raman"]["fit"]["prefit"]["a1g_snr_hard_min"] = 7.5

    edited = _write_thresholds(tmp_path / "edited.yaml", _edit)
    config = load_pipeline_config(RAMAN_CONFIG_DIR, thresholds_path=edited)
    assert config["raman"]["fit"]["prefit"]["a1g_snr_hard_min"] == 7.5

    typo = _write_thresholds(tmp_path / "typo.yaml", lambda p: p.update({"ramen": {}}))
    with pytest.raises(ValueError, match="ramen"):
        load_pipeline_config(RAMAN_CONFIG_DIR, thresholds_path=typo)

    missing = _write_thresholds(
        tmp_path / "missing.yaml", lambda p: p["raman"]["fit"]["prefit"].pop("a1g_snr_soft_min")
    )
    with pytest.raises(ValueError, match="a1g_snr_soft_min"):
        load_pipeline_config(RAMAN_CONFIG_DIR, thresholds_path=missing)


def test_frozen_thresholds_prefer_exe_dir_then_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exe_dir = tmp_path / "mos2-analysis"
    bundle_dir = exe_dir / "_internal"
    bundle_dir.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_dir), raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "mos2-analysis.exe"))

    assert runtime_paths.thresholds_path() == bundle_dir.resolve() / "thresholds.yaml"
    (exe_dir / "thresholds.yaml").write_text("{}", encoding="utf-8")
    assert runtime_paths.thresholds_path() == exe_dir.resolve() / "thresholds.yaml"


def test_quality_flag_threshold_reaches_report(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # r2 can never reach 1.01, so every fitted row must be flagged low_r2.
    def _edit(payload: dict) -> None:
        payload["raman"]["quality_flags"]["r2_min"] = 1.01

    edited = _write_thresholds(tmp_path / "strict.yaml", _edit)
    monkeypatch.setattr(runtime_paths, "thresholds_path", lambda: edited)

    context = build_default_context(run_id="strict_r2", artifact_dir=tmp_path, config_dir=RAMAN_CONFIG_DIR)
    stages = build_default_stages(config=context.config)
    result = run_pipeline(raw_spectra=generate_dummy_spectra(count=2), stages=stages, context=context)

    report_path = next(Path(r.path) for r in result.reports if str(r.path).endswith("_fit_report.json"))
    rows = json.loads(report_path.read_text(encoding="utf-8"))["spectra"]
    assert rows
    assert all("low_r2" in row["attention_reasons"] for row in rows)
