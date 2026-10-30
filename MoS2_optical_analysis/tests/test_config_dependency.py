"""Every value in config.yaml must actually drive the code, with no copy of it hidden in the code.

Comparing results before/after moving values into config.yaml cannot prove this (the values were
copied, so results match either way). Instead these tests trace which config.yaml keys the code
reads while running the real Raman/PL pipelines and the GUI setting readers.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from fitting.mos2_core.core.default_stages import build_default_context, build_default_stages
from fitting.mos2_core.core.pipeline import run_pipeline
from fitting.mos2_core.io import config_access as cfgx
from fitting.mos2_core.io import generate_dummy_spectra, load_pipeline_config
from fitting.mos2_pl.run_raw_pipeline import _pl_intensity_density_correction_enabled
from fitting.mos2_pl.sample_data import generate_dummy_pl_spectra
from gui.components.science_settings import fwhm_warn_limits, flagged_legacy_thresholds, strain_doping_settings

WORKSPACE = Path(__file__).resolve().parents[1]
RAMAN_CONFIG_DIR = WORKSPACE / "fitting" / "mos2_raman" / "config"
USER_CONFIG = WORKSPACE / "config.yaml"


class _Tracked(dict):
    """dict that records which keys are read strictly (`cfg[key]`) or with a fallback (`cfg.get`)."""

    def __init__(self, data: dict, path: str, log: dict[str, set[str]]) -> None:
        super().__init__({k: _track(v, f"{path}.{k}" if path else str(k), log) for k, v in data.items()})
        self._path = path
        self._log = log

    def _key_path(self, key: Any) -> str:
        return f"{self._path}.{key}" if self._path else str(key)

    def __getitem__(self, key: Any) -> Any:
        self._log["strict"].add(self._key_path(key))
        return super().__getitem__(key)

    def get(self, key: Any, default: Any = None) -> Any:
        if key in self:
            self._log["fallback"].add(self._key_path(key))
        return super().get(key, default)

    def __deepcopy__(self, memo: dict) -> "_Tracked":
        return _Tracked({k: copy.deepcopy(dict.__getitem__(self, k), memo) for k in self}, self._path, self._log)


def _track(value: Any, path: str, log: dict[str, set[str]]) -> Any:
    if isinstance(value, _Tracked):
        return value
    if isinstance(value, dict):
        return _Tracked(value, path, log)
    return value


def _leaf_paths(node: Any, path: str = "") -> list[str]:
    if isinstance(node, dict):
        return [leaf for key, value in node.items() for leaf in _leaf_paths(value, f"{path}.{key}" if path else str(key))]
    return [path]


def _run_every_config_consumer(config: dict, out_dir: Path) -> None:
    """Real Raman + PL pipelines (fit, select, QC, review, report) and the GUI setting readers."""
    for run_id, spectra in (
        ("dep_raman", generate_dummy_spectra(count=2)),
        ("dep_pl", generate_dummy_pl_spectra(count=2)),
    ):
        context = build_default_context(run_id=run_id, artifact_dir=out_dir, config=config)
        run_pipeline(raw_spectra=spectra, stages=build_default_stages(config=context.config), context=context)
    _pl_intensity_density_correction_enabled(config)
    graph_cfg = config["raman_graph"]
    fwhm_warn_limits(graph_cfg)
    flagged_legacy_thresholds(graph_cfg)
    strain_doping_settings(graph_cfg)


@pytest.fixture(scope="module")
def access_log(tmp_path_factory: pytest.TempPathFactory) -> dict[str, set[str]]:
    log: dict[str, set[str]] = {"strict": set(), "fallback": set()}
    config = _track(load_pipeline_config(RAMAN_CONFIG_DIR), "", log)
    _run_every_config_consumer(config, tmp_path_factory.mktemp("dep_runs"))
    return log


def _config_leaves() -> list[str]:
    return _leaf_paths(yaml.safe_load(USER_CONFIG.read_text(encoding="utf-8")))


def test_every_config_yaml_value_is_read_by_the_code(access_log: dict[str, set[str]]) -> None:
    unread = [leaf for leaf in _config_leaves() if leaf not in access_log["strict"]]
    assert not unread, f"config.yaml keys that no code reads (changing them does nothing): {unread}"


def test_no_config_yaml_value_has_a_fallback_copy_in_code(access_log: dict[str, set[str]]) -> None:
    # `.get(key, default)` on a config.yaml key means the code keeps its own value for when the key is missing.
    with_fallback = sorted(leaf for leaf in _config_leaves() if leaf in access_log["fallback"])
    assert not with_fallback, f"config.yaml keys read with a code-side default: {with_fallback}"


@pytest.mark.parametrize(
    "leaf",
    [
        "raman.fit.e2g_init",
        "raman.fit.prefit.noise_windows.fallback_percentile",
        "raman.post_selection_qc.delta_outlier.absolute_range.min",
        "raman.quality_flags.r2_min",
        "pl.fit.components.a0.fwhm_max",
        "pl.fit.spike_check.span_percentiles",
        "pl.despike.threshold",
        "review.high_rmse_threshold",
    ],
)
def test_missing_key_stops_the_run_and_names_the_key(leaf: str, tmp_path: Path) -> None:
    config = load_pipeline_config(RAMAN_CONFIG_DIR)
    *parents, last = leaf.split(".")
    node = config
    for key in parents:
        node = node[key]
    del node[last]
    with pytest.raises(cfgx.ConfigKeyError, match=leaf.replace(".", r"\.")):
        _run_every_config_consumer(config, tmp_path)
