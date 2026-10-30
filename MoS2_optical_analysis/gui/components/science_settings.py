"""Scientific settings the GUI reads from config.yaml (`raman_graph` section).

Pure functions over the merged graph config so every page reads them the same way and a missing
key fails with its full path instead of falling back to a number hidden in page code.
"""

from __future__ import annotations

from typing import Any, Mapping

from fitting.mos2_core.io import config_access as cfgx


def fwhm_warn_limits(graph_cfg: Mapping[str, Any]) -> dict[str, float]:
    path = "raman_graph.all_spectra_viewer.fwhm_warn"
    warn = cfgx.section(cfgx.section(graph_cfg, "all_spectra_viewer", "raman_graph"), "fwhm_warn", path.rsplit(".", 1)[0])
    return {key: cfgx.number(warn, key, path) for key in ("raman_min", "raman_max", "pl_max")}


def flagged_legacy_thresholds(graph_cfg: Mapping[str, Any]) -> dict[str, float]:
    path = "raman_graph.flagged_spectra.legacy_thresholds"
    legacy = cfgx.section(cfgx.section(graph_cfg, "flagged_spectra", "raman_graph"), "legacy_thresholds", path.rsplit(".", 1)[0])
    return {key: cfgx.number(legacy, key, path) for key in ("rmse_threshold", "r2_lower_bound", "delta_max")}


def strain_doping_settings(graph_cfg: Mapping[str, Any]) -> dict[str, Any]:
    base = "raman_graph.sample_comparison"
    sample = cfgx.section(graph_cfg, "sample_comparison", "raman_graph")
    coeffs = cfgx.section(sample, "coefficients", base)
    isolines = cfgx.section(sample, "absolute_isolines", base)
    return {
        "coefficients": {key: cfgx.number(coeffs, key, f"{base}.coefficients") for key in ("s_e", "s_a", "d_e", "d_a")},
        "eps_range": cfgx.pair(isolines, "eps_range", f"{base}.absolute_isolines"),
        "n_range": cfgx.pair(isolines, "n_range", f"{base}.absolute_isolines"),
    }
