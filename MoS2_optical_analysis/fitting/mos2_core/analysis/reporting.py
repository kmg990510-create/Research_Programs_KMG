"""Report generation implementations."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from ..core.interfaces import ReportGenerationStage
from ..core.types import PipelineContext, PipelineResult, ReportArtifact
from ..io import config_access as cfgx


def _to_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _median(values: list[float]) -> float:
    values = sorted(values)
    n = len(values)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 1:
        return values[mid]
    return 0.5 * (values[mid - 1] + values[mid])


def _mad(values: list[float], med: float) -> float:
    if not values:
        return 0.0
    deviations = [abs(v - med) for v in values]
    return _median(deviations)


def _is_outlier(
    value: float | None,
    med: float,
    sigma: float,
    fallback_abs: float,
    sigma_k: float,
) -> bool:
    if value is None:
        return False
    if sigma > 1.0e-9:
        return abs(value - med) > max(fallback_abs, sigma_k * sigma)
    return abs(value - med) > fallback_abs


def _normalize_reason_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _check_peak_order(row: dict[str, object]) -> bool:
    ordered = []
    for key in ["lo_position", "e2g_position", "a1g_position", "zo_position", "la_position"]:
        value = _to_float(row.get(key))
        if value is None:
            continue
        ordered.append(value)
    return all(ordered[i] < ordered[i + 1] for i in range(len(ordered) - 1))


def _fwhm_bounds_by_peak_from_config(config: object, modality: str) -> dict[str, tuple[float, float]]:
    """Allowed FWHM range per peak, straight from the fit bounds in config.yaml."""
    fit_cfg = cfgx.section(cfgx.section(config, modality, ""), "fit", modality)
    bounds: dict[str, tuple[float, float]] = {}
    if modality == "pl":
        components = cfgx.section(fit_cfg, "components", "pl.fit")
        for name in components:
            spec = cfgx.section(components, name, "pl.fit.components")
            where = f"pl.fit.components.{name}"
            bounds[str(name).lower()] = (cfgx.number(spec, "fwhm_min", where), cfgx.number(spec, "fwhm_max", where))
        return bounds
    sigma_cfg = cfgx.section(fit_cfg, "sigma_bounds_by_peak", "raman.fit")
    for peak_name in ("lo", "e2g", "a1g", "zo", "la"):
        sigma_min, sigma_max = cfgx.pair(sigma_cfg, peak_name, "raman.fit.sigma_bounds_by_peak")
        # Raman peaks are pseudo-Voigt: FWHM = 2 * sigma exactly.
        bounds[peak_name] = (2.0 * sigma_min, 2.0 * sigma_max)
    return bounds


def _resolve_run_modality(result: PipelineResult, context: PipelineContext) -> str:
    state_modality = str(context.state.get("run_modality", "")).strip().lower()
    if state_modality:
        return state_modality

    raw_counts = context.state.get("input_modality_counts", {})
    if isinstance(raw_counts, dict):
        normalized = {
            str(k).strip().lower(): int(v)
            for k, v in raw_counts.items()
            if str(k).strip()
        }
        if len(normalized) == 1:
            return next(iter(normalized.keys()))
        if len(normalized) > 1:
            return "mixed"

    metadata_index = context.state.get("spectrum_metadata", {})
    modalities: set[str] = set()
    if isinstance(metadata_index, dict):
        for accepted in result.accepted:
            meta = metadata_index.get(accepted.spectrum_id, {})
            if isinstance(meta, dict):
                modality = str(meta.get("modality", "")).strip().lower()
                if modality:
                    modalities.add(modality)

    if len(modalities) == 1:
        return next(iter(modalities))
    if len(modalities) > 1:
        return "mixed"
    return "raman"


def _fwhm_normal_band_by_peak(
    fwhm_bounds_by_peak: dict[str, tuple[float, float]],
    margin_ratio: float,
) -> dict[str, tuple[float, float]]:
    bands: dict[str, tuple[float, float]] = {}
    for peak_name, (fwhm_min, fwhm_max) in fwhm_bounds_by_peak.items():
        span = max(fwhm_max - fwhm_min, 0.0)
        margin = margin_ratio * span
        bands[peak_name] = (fwhm_min + margin, fwhm_max - margin)
    return bands


class RamanFitReportGenerator(ReportGenerationStage):
    """
    Write fit-centric JSON/CSV reports for Raman analysis.

    Outputs:
    - <run_id>_fit_report.json
    - <run_id>_fit_parameters.csv
    """

    def __init__(self, output_subdir: str = "data/results") -> None:
        self.output_subdir = output_subdir

    def run(
        self,
        result: PipelineResult,
        context: PipelineContext,
    ) -> list[ReportArtifact]:
        root = context.artifact_dir or Path.cwd()
        run_modality = _resolve_run_modality(result, context)
        out_dir = root / self.output_subdir / run_modality / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)

        run_id = context.run_id or "run"
        json_path = out_dir / f"{run_id}_fit_report.json"
        csv_path = out_dir / f"{run_id}_fit_parameters.csv"
        metadata_index = context.state.get("spectrum_metadata", {})
        fit_ensemble_cache = context.state.get("fit_ensemble_cache", {})
        active_cfg = context.config.get(run_modality, {}) if isinstance(context.config, dict) else {}
        if not isinstance(active_cfg, dict):
            active_cfg = {}
        report_export_cfg = (
            active_cfg.get("report_export", {})
            if isinstance(active_cfg, dict)
            else {}
        )
        include_selected_fitted_y = bool(report_export_cfg.get("include_selected_fitted_y", False))
        include_all_candidates = bool(report_export_cfg.get("include_all_candidates", True))

        spectra_rows: list[dict[str, object]] = []
        for accepted in result.accepted:
            meta = metadata_index.get(accepted.spectrum_id, {})
            all_candidates_full = fit_ensemble_cache.get(accepted.spectrum_id, [])
            if not isinstance(all_candidates_full, list):
                all_candidates_full = []
            all_candidates = all_candidates_full if include_all_candidates else []
            fit_params = (
                dict(accepted.fit.params)
                if isinstance(accepted.fit.params, dict)
                else {}
            )
            fit_metrics = (
                dict(accepted.fit.metrics)
                if isinstance(accepted.fit.metrics, dict)
                else {}
            )
            row = {
                "spectrum_id": accepted.spectrum_id,
                "source_file": meta.get("source_file"),
                "source_extension": meta.get("source_extension"),
                "x_unit": meta.get("x_unit"),
                "original_x_unit": meta.get("original_x_unit"),
                "x_conversion": meta.get("x_conversion"),
                "intensity_density_correction": meta.get("intensity_density_correction"),
                "intensity_conversion": meta.get("intensity_conversion"),
                "original_x_min_nm": meta.get("original_x_min_nm"),
                "original_x_max_nm": meta.get("original_x_max_nm"),
                "temperature_k": meta.get("temperature_k"),
                "treatment_label": meta.get("treatment_label"),
                "calibration_offset": meta.get("calibration_offset"),
                "calibration_success": meta.get("calibration_success"),
                "si_area": meta.get("si_area"),
                "map_id": meta.get("map_id"),
                "map_x": meta.get("map_x"),
                "map_y": meta.get("map_y"),
                "modality": str(meta.get("modality", run_modality)).strip().lower() or run_modality,
                "selected_model": accepted.fit.model_name,
                "fit_params": fit_params,
                "fit_metrics": fit_metrics,
                "reviewed": accepted.reviewed,
                "review_decision": accepted.review_decision.decision
                if accepted.review_decision
                else "auto",
                "all_candidates": all_candidates,
                "candidate_count": len(all_candidates_full),
            }
            row.update(fit_params)
            row.update(fit_metrics)
            row["selected_model"] = accepted.fit.model_name
            row.setdefault("fit_status", "valid")
            row.setdefault("invalid_reasons", [])
            row.setdefault("attention_reasons", [])
            if include_selected_fitted_y:
                row["fitted_y"] = accepted.fit.fitted_y
            spectra_rows.append(row)

        rmse_values = [v for v in (_to_float(r.get("rmse")) for r in spectra_rows) if v is not None]
        rmse_med = _median(rmse_values) if rmse_values else 0.0
        rmse_sigma = 1.4826 * _mad(rmse_values, rmse_med) if rmse_values else 0.0
        # Quality-flag thresholds come from config.yaml (`{modality}.quality_flags`).
        # A mixed-modality run (dummy/smoke data) is judged with the Raman settings.
        qc_modality = run_modality if run_modality in {"raman", "pl"} else "raman"
        qf = f"{qc_modality}.quality_flags"
        quality_cfg = cfgx.section(cfgx.section(context.config, qc_modality, ""), "quality_flags", qc_modality)
        r2_min = cfgx.number(quality_cfg, "r2_min", qf)
        rmse_sigma_k = cfgx.number(quality_cfg, "rmse_outlier_sigma_k", qf)
        rmse_fallback_abs = cfgx.number(quality_cfg, "rmse_outlier_fallback_abs", qf)
        fwhm_margin_ratio = cfgx.number(quality_cfg, "fwhm_band_margin_ratio", qf)
        fwhm_normal_band = _fwhm_normal_band_by_peak(
            _fwhm_bounds_by_peak_from_config(context.config, qc_modality),
            margin_ratio=fwhm_margin_ratio,
        )
        pl_qc_component_names = (
            [name.lower() for name in cfgx.string_list(quality_cfg, "fwhm_check_components", qf)]
            if qc_modality == "pl"
            else []
        )

        attention_count = 0
        invalid_count = 0
        for row in spectra_rows:
            flags: list[str] = []

            delta = _to_float(row.get("delta_e2g_a1g"))
            rmse = _to_float(row.get("rmse"))
            r2 = _to_float(row.get("r2"))
            fit_status = str(row.get("fit_status", "valid")).strip().lower()
            invalid_reasons = _normalize_reason_list(row.get("invalid_reasons"))
            attention_reasons = _normalize_reason_list(row.get("attention_reasons"))

            if _is_outlier(rmse, rmse_med, rmse_sigma, fallback_abs=rmse_fallback_abs, sigma_k=rmse_sigma_k):
                flags.append("rmse_outlier_vs_dataset")
            if r2 is not None and r2 < r2_min:
                flags.append("low_r2")

            if run_modality == "pl":
                has_component_fwhm = any(
                    _to_float(row.get(f"{name}_fwhm")) is not None
                    for name in pl_qc_component_names
                )
                peak_names_for_band = pl_qc_component_names if has_component_fwhm else ["pl"]
            else:
                peak_names_for_band = ["lo", "e2g", "a1g", "zo", "la"]

            for peak_name in peak_names_for_band:
                key = f"{peak_name}_fwhm"
                value = _to_float(row.get(key))
                if value is None:
                    continue
                normal_band = fwhm_normal_band.get(peak_name)
                if normal_band is None:
                    continue
                normal_min, normal_max = normal_band
                if value < normal_min or value > normal_max:
                    flags.append(f"{key}_outside_normal_band")

            if not _check_peak_order(row):
                flags.append("peak_order_violation")

            flags = list(dict.fromkeys(flags))
            if fit_status == "invalid" and not invalid_reasons:
                invalid_reasons = ["invalid_fit_status"]

            if fit_status == "invalid" or invalid_reasons:
                fit_status = "invalid"
            elif fit_status == "attention" or attention_reasons or flags:
                fit_status = "attention"
            else:
                fit_status = "valid"

            attention_reasons = list(dict.fromkeys(attention_reasons + flags))
            quality_flags = list(dict.fromkeys(invalid_reasons + attention_reasons))

            row["fit_status"] = fit_status
            row["invalid_reasons"] = invalid_reasons
            row["attention_reasons"] = attention_reasons
            row["quality_flags"] = quality_flags
            row["needs_attention"] = fit_status in {"attention", "invalid"} or bool(quality_flags)
            row["attention_score"] = len(quality_flags)

            if fit_status == "invalid":
                invalid_count += 1
            if row["needs_attention"]:
                attention_count += 1

        payload = {
            "run_id": run_id,
            "modality": run_modality,
            "report_dir": str(out_dir),
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "counts": {
                "qc_total": len(result.qc),
                "flagged": len(result.flagged),
                "decisions": len(result.decisions),
                "accepted": len(result.accepted),
                "parameters": len(result.parameters),
                "maps": len(result.maps),
            },
            "selection_metric_usage": context.state.get("selection_metric_usage", {}),
            "fit_failure_count": len(context.state.get("fit_failures", [])),
            "attention_count": attention_count,
            "invalid_count": invalid_count,
            "config": {
                "raman": context.config.get("raman", {}),
                "pl": context.config.get("pl", {}),
                "baseline": context.config.get("baseline", {}),
                "review": context.config.get("review", {}),
            },
            "map_summary": [m.summary for m in result.maps],
            "spectra": spectra_rows,
        }
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        fieldnames = [
            "spectrum_id",
            "source_file",
            "calibration_offset",
            "calibration_success",
            "si_area",
            "map_id",
            "map_x",
            "map_y",
            "modality",
            "selected_model",
            "fit_status",
            "invalid_reasons",
            "attention_reasons",
            "lo_position",
            "e2g_position",
            "a1g_position",
            "zo_position",
            "la_position",
            "delta_e2g_a1g",
            "lo_fwhm",
            "e2g_fwhm",
            "a1g_fwhm",
            "zo_fwhm",
            "la_fwhm",
            "lo_area",
            "e2g_area",
            "a1g_area",
            "zo_area",
            "la_area",
            "lo_height",
            "e2g_height",
            "a1g_height",
            "zo_height",
            "la_height",
            "bg_slope",
            "bg_intercept",
            "rmse",
            "r2",
            "aic",
            "bic",
            "prefit_noise_std",
            "prefit_e2g_peak_height",
            "prefit_a1g_peak_height",
            "prefit_e2g_snr",
            "prefit_a1g_snr",
            "attention_score",
            "needs_attention",
            "reviewed",
            "review_decision",
        ]
        if run_modality == "pl":
            insert_at = fieldnames.index("attention_reasons") + 1
            fieldnames[insert_at:insert_at] = ["pl_position", "pl_fwhm", "pl_area", "pl_height"]
        reserved_for_json_only = {"all_candidates", "fit_params", "fit_metrics", "fitted_y"}
        known_fields = set(fieldnames)
        extra_fieldnames = sorted(
            {
                str(key)
                for row in spectra_rows
                for key in row.keys()
                if str(key) not in known_fields and str(key) not in reserved_for_json_only
            }
        )
        fieldnames.extend(extra_fieldnames)
        with csv_path.open("w", newline="", encoding="utf-8") as fp:
            writer = csv.DictWriter(fp, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(spectra_rows)

        return [
            ReportArtifact(
                report_id=f"{run_id}_fit_report_json",
                path=json_path,
                metadata={"format": "json"},
            ),
            ReportArtifact(
                report_id=f"{run_id}_fit_report_csv",
                path=csv_path,
                metadata={"format": "csv"},
            ),
        ]


class JsonSummaryReportGenerator(RamanFitReportGenerator):
    """Backward-compatible alias to fit-centric report generator."""
