"""YAML configuration loader for the MoS2 spectra pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any


_SECTION_FILES = {
    "raman": "raman.yaml",
    "raman_graph": "raman_graph.yaml",
    "pl": "pl.yaml",
    "baseline": "baseline.yaml",
    "review": "review.yaml",
}  # one file per top-level section


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "PyYAML is required for config loading. Install with: pip install PyYAML"
        ) from exc

    if not path.exists():
        raise FileNotFoundError(f"Required config file not found: {path}")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        raise ValueError(f"Config file is empty: {path}")
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a mapping: {path}")
    return data


def _ensure_required_keys(section: str, payload: dict[str, Any], source_path: Path) -> None:
    required_top_level: dict[str, tuple[str, ...]] = {
        "raman": ("models", "selection_metric", "fit", "si_calibration"),
        "raman_graph": ("sample_comparison", "all_spectra_viewer", "flagged_spectra"),
        "pl": ("models", "selection_metric"),
        "baseline": ("default_method", "default_score", "methods"),
        "review": ("confidence_threshold", "auto_approve_stub"),
    }
    missing = [key for key in required_top_level.get(section, ()) if key not in payload]
    if missing:
        raise ValueError(
            f"Missing required key(s) in {source_path}: {', '.join(missing)}"
        )

    if section == "raman":
        fit = payload.get("fit")
        if not isinstance(fit, dict):
            raise ValueError(f"'fit' must be a mapping in {source_path}")
        required_fit_keys = (
            "x_min",
            "x_max",
            "compare_x_min",
            "compare_x_max",
            "enforce_peak_order",
            "e2g_init",
            "a1g_init",
            "lo_offset_from_e2g",
            "zo_offset_from_a1g",
            "la_offset_from_a1g",
            "height_scales",
            "center_tolerance_by_model",
            "e2g_min",
            "e2g_max",
            "a1g_min",
            "a1g_max",
            "sigma_min",
            "sigma_max",
            "sigma_bounds_by_peak",
            "prefit",
        )
        missing_fit = [key for key in required_fit_keys if key not in fit]
        if missing_fit:
            raise ValueError(
                f"Missing required fit key(s) in {source_path}: {', '.join(missing_fit)}"
            )

        anchor_cfg = fit.get("two_stage_anchor")
        if not isinstance(anchor_cfg, dict):
            raise ValueError(f"'fit.two_stage_anchor' must be a mapping in {source_path}")
        missing_anchor_keys = [k for k in ("enabled", "window") if k not in anchor_cfg]
        if missing_anchor_keys:
            raise ValueError(
                "Missing required fit.two_stage_anchor key(s) in "
                f"{source_path}: {', '.join(missing_anchor_keys)}"
            )

        auto_refine_cfg = fit.get("auto_refine")
        if auto_refine_cfg is not None:
            if not isinstance(auto_refine_cfg, dict):
                raise ValueError(f"'fit.auto_refine' must be a mapping in {source_path}")
            missing_auto_refine_keys = [k for k in ("enabled", "min_rmse_improvement") if k not in auto_refine_cfg]
            if missing_auto_refine_keys:
                raise ValueError(
                    "Missing required fit.auto_refine key(s) in "
                    f"{source_path}: {', '.join(missing_auto_refine_keys)}"
                )

        prefit = fit.get("prefit")
        if not isinstance(prefit, dict):
            raise ValueError(f"'fit.prefit' must be a mapping in {source_path}")
        required_prefit_keys = (
            "enabled",
            "peak_window_half_width",
            "e2g_snr_hard_min",
            "e2g_snr_soft_min",
            "a1g_snr_hard_min",
            "a1g_snr_soft_min",
            "noise_windows",
        )
        missing_prefit = [key for key in required_prefit_keys if key not in prefit]
        if missing_prefit:
            raise ValueError(
                f"Missing required fit.prefit key(s) in {source_path}: {', '.join(missing_prefit)}"
            )
        noise_windows = prefit.get("noise_windows")
        if not isinstance(noise_windows, dict):
            raise ValueError(f"'fit.prefit.noise_windows' must be a mapping in {source_path}")
        required_noise_window_keys = ("left", "right")
        missing_noise_window = [key for key in required_noise_window_keys if key not in noise_windows]
        if missing_noise_window:
            raise ValueError(
                "Missing required fit.prefit.noise_windows key(s) in "
                f"{source_path}: {', '.join(missing_noise_window)}"
            )

        si = payload.get("si_calibration")
        if not isinstance(si, dict):
            raise ValueError(f"'si_calibration' must be a mapping in {source_path}")
        required_si_keys = (
            "enabled",
            "window_min",
            "window_max",
            "target_peak",
            "min_points",
            "initial_width",
            "max_abs_offset",
        )
        missing_si = [key for key in required_si_keys if key not in si]
        if missing_si:
            raise ValueError(
                f"Missing required si_calibration key(s) in {source_path}: {', '.join(missing_si)}"
            )

    if section == "raman_graph":
        sample_comparison = payload.get("sample_comparison")
        if not isinstance(sample_comparison, dict):
            raise ValueError(f"'sample_comparison' must be a mapping in {source_path}")
        required_sample_keys = (
            "default_report_count",
            "status_filter",
            "coefficients",
            "center_metric_default",
            "error_metric_default",
            "overlay_scatter_default",
            "absolute_isolines",
        )
        missing_sample = [key for key in required_sample_keys if key not in sample_comparison]
        if missing_sample:
            raise ValueError(
                f"Missing required sample_comparison key(s) in {source_path}: {', '.join(missing_sample)}"
            )

        status_filter = sample_comparison.get("status_filter")
        if not isinstance(status_filter, dict):
            raise ValueError(f"'sample_comparison.status_filter' must be a mapping in {source_path}")
        required_status_filter_keys = ("enabled_default", "allowed_default")
        missing_status_filter = [key for key in required_status_filter_keys if key not in status_filter]
        if missing_status_filter:
            raise ValueError(
                "Missing required sample_comparison.status_filter key(s) in "
                f"{source_path}: {', '.join(missing_status_filter)}"
            )

        coeffs = sample_comparison.get("coefficients")
        if not isinstance(coeffs, dict):
            raise ValueError(f"'sample_comparison.coefficients' must be a mapping in {source_path}")
        required_coeff_keys = ("s_e", "s_a", "d_e", "d_a")
        missing_coeffs = [key for key in required_coeff_keys if key not in coeffs]
        if missing_coeffs:
            raise ValueError(
                "Missing required sample_comparison.coefficients key(s) in "
                f"{source_path}: {', '.join(missing_coeffs)}"
            )

        absolute_isolines = sample_comparison.get("absolute_isolines")
        if not isinstance(absolute_isolines, dict):
            raise ValueError(
                f"'sample_comparison.absolute_isolines' must be a mapping in {source_path}"
            )
        required_iso_keys = ("show_default", "density_default", "steps")
        missing_iso = [key for key in required_iso_keys if key not in absolute_isolines]
        if missing_iso:
            raise ValueError(
                "Missing required sample_comparison.absolute_isolines key(s) in "
                f"{source_path}: {', '.join(missing_iso)}"
            )

        all_spectra = payload.get("all_spectra_viewer")
        if not isinstance(all_spectra, dict):
            raise ValueError(f"'all_spectra_viewer' must be a mapping in {source_path}")
        x_window = all_spectra.get("x_window")
        if not isinstance(x_window, dict):
            raise ValueError(f"'all_spectra_viewer.x_window' must be a mapping in {source_path}")
        required_x_window_keys = ("fallback_min", "fallback_max", "peak_padding")
        missing_x_window = [key for key in required_x_window_keys if key not in x_window]
        if missing_x_window:
            raise ValueError(
                "Missing required all_spectra_viewer.x_window key(s) in "
                f"{source_path}: {', '.join(missing_x_window)}"
            )

        flagged = payload.get("flagged_spectra")
        if not isinstance(flagged, dict):
            raise ValueError(f"'flagged_spectra' must be a mapping in {source_path}")
        legacy_thresholds = flagged.get("legacy_thresholds")
        if not isinstance(legacy_thresholds, dict):
            raise ValueError(
                f"'flagged_spectra.legacy_thresholds' must be a mapping in {source_path}"
            )
        required_legacy_keys = ("rmse_threshold", "r2_lower_bound", "delta_max")
        missing_legacy = [key for key in required_legacy_keys if key not in legacy_thresholds]
        if missing_legacy:
            raise ValueError(
                "Missing required flagged_spectra.legacy_thresholds key(s) in "
                f"{source_path}: {', '.join(missing_legacy)}"
            )


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def load_pipeline_config(
    config_dir: str | Path,
    user_config_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Load pipeline config from YAML files only.

    All section files are required, and required keys must be present.

    Expected files under `config_dir`:
    - raman.yaml
    - raman_graph.yaml
    - pl.yaml
    - baseline.yaml
    - review.yaml

    Scientific values (peaks, bounds, windows, thresholds) live in one user-editable `config.yaml`
    (default: `runtime_paths.user_config_path()`); its top-level keys are section
    names and are deep-merged over the section files before key validation.
    """

    root = Path(config_dir)
    if not root.exists():
        raise FileNotFoundError(f"Config directory not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Config path is not a directory: {root}")

    if user_config_path is None:
        # Local import: `core` imports this module at package import time.
        from ..core.runtime_paths import user_config_path as _default_user_config_path

        user_config_path = _default_user_config_path()
    user_config_file = Path(user_config_path)
    user_config = _load_yaml_mapping(user_config_file)
    unknown = sorted(str(key) for key in user_config if key not in _SECTION_FILES)
    if unknown:
        raise ValueError(
            f"Unknown section(s) in {user_config_file}: {', '.join(unknown)} "
            f"(allowed: {', '.join(_SECTION_FILES)})"
        )

    config: dict[str, Any] = {}
    for section, filename in _SECTION_FILES.items():
        source_path = root / filename
        loaded = _load_yaml_mapping(source_path)
        override = user_config.get(section)
        if override is not None:
            if not isinstance(override, dict):
                raise ValueError(f"'{section}' must be a mapping in {user_config_file}")
            loaded = _deep_merge(loaded, override)
        try:
            _ensure_required_keys(section, loaded, source_path)
        except ValueError as exc:
            raise ValueError(f"{exc} (after merging {user_config_file})") from exc
        config[section] = loaded

    return config
