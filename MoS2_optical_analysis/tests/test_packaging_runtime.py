from __future__ import annotations

import concurrent.futures
import sys
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import pytest

from fitting.mos2_core.core import runtime_paths
from fitting.mos2_core.core.default_stages import build_default_context, build_default_stages
from fitting.mos2_core.io import generate_dummy_spectra
from fitting.mos2_core.review.refit_api import SingleSpectrumRefitAPI

RAMAN_CONFIG_DIR = Path(__file__).resolve().parents[1] / "fitting" / "mos2_raman" / "config"


def test_source_run_config_dir_is_workspace_config() -> None:
    assert runtime_paths.raman_config_dir() == RAMAN_CONFIG_DIR


def test_frozen_run_reads_config_from_bundle_and_data_from_exe_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exe_dir = tmp_path / "mos2-analysis"
    bundle_dir = exe_dir / "_internal"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_dir), raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "mos2-analysis.exe"))

    expected_config = bundle_dir.resolve() / "fitting" / "mos2_raman" / "config"
    assert runtime_paths.raman_config_dir() == expected_config
    assert runtime_paths.runtime_project_root(__file__, 1) == exe_dir.resolve()
    # All Spectra passes the exe folder as project_root; config must still come from the bundle.
    api = SingleSpectrumRefitAPI(project_root=exe_dir)
    assert api.config_dir == expected_config
    assert api.project_root == exe_dir.resolve()


class _BrokenPoolExecutor:
    """Stands in for a process pool whose children die on startup."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self) -> "_BrokenPoolExecutor":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def submit(self, fn, /, *args, **kwargs) -> concurrent.futures.Future:
        future: concurrent.futures.Future = concurrent.futures.Future()
        future.set_exception(BrokenProcessPool("child process terminated abruptly"))
        return future


def test_broken_process_pool_falls_back_to_sequential(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(concurrent.futures, "ProcessPoolExecutor", _BrokenPoolExecutor)
    context = build_default_context(run_id="broken_pool", artifact_dir=tmp_path, config_dir=RAMAN_CONFIG_DIR)
    context.state["fit_workers"] = 2
    stages = build_default_stages(config=context.config)

    passed, _ = stages.qc.run(generate_dummy_spectra(count=3), context)
    preprocessed = stages.preprocess.run(passed, context)
    baselines = stages.baseline_ensemble.run(preprocessed, context)
    ensemble = stages.model_ensemble_fitting.run(preprocessed, baselines, context)

    model_names = {c.model_name for result in ensemble.values() for c in result.candidates}
    assert len(ensemble) == 3
    assert "fit_worker_exception" not in model_names
    assert any(name.startswith("peak_") for name in model_names)
    assert any(f["model_name"] == "process_pool_init" for f in context.state["fit_failures"])
