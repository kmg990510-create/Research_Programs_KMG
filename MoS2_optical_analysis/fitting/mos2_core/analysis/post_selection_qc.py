"""Post-selection QC rules applied before confidence/review stages."""

from __future__ import annotations

from typing import Mapping

import numpy as np

from ..core.interfaces import PostSelectionQCStage
from ..core.types import FitCandidate, PipelineContext, SelectionResult
from ..io import config_access as cfgx


def _to_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _normalize_reason_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _mad_sigma(values: np.ndarray) -> tuple[float, float]:
    if values.size == 0:
        return 0.0, 0.0
    med = float(np.median(values))
    mad = float(np.median(np.abs(values - med)))
    return med, float(1.4826 * mad)


def _choice(value: str, allowed: set[str], where: str) -> str:
    if value not in allowed:
        raise cfgx.ConfigKeyError(f"config.yaml: '{where}' must be one of {sorted(allowed)} (got {value!r})")
    return value


def _statuses(mapping: Mapping[str, object], key: str, path: str) -> list[str]:
    values = [v.lower() for v in cfgx.string_list(mapping, key, path)]
    for value in values:
        _choice(value, {"valid", "attention"}, f"{path}.{key}")
    if not values:
        raise cfgx.ConfigKeyError(f"config.yaml: '{path}.{key}' must list at least one status")
    return values


class MahalanobisPostSelectionQC(PostSelectionQCStage):
    """
    Invalidate geometrically implausible E2g/A1g locations using Mahalanobis distance.

    Reference distribution is built from currently selected valid spectra only.
    """

    def run(
        self,
        selections: Mapping[str, SelectionResult],
        context: PipelineContext,
    ) -> Mapping[str, SelectionResult]:
        q = "raman.post_selection_qc"
        qc_cfg = cfgx.section(cfgx.section(context.config, "raman", ""), "post_selection_qc", "raman")
        enabled = cfgx.flag(qc_cfg, "enabled", q)
        mahalanobis_enabled = cfgx.flag(cfgx.section(qc_cfg, "mahalanobis_outlier", q), "enabled", f"{q}.mahalanobis_outlier")
        mahalanobis_distance_threshold = cfgx.number(qc_cfg, "mahalanobis_distance_threshold", q)
        min_reference_valid_samples = cfgx.integer(qc_cfg, "min_reference_valid_samples", q)
        covariance_regularization = cfgx.number(qc_cfg, "covariance_regularization", q)

        d = f"{q}.delta_outlier"
        delta_cfg = cfgx.section(qc_cfg, "delta_outlier", q)
        delta_enabled = cfgx.flag(delta_cfg, "enabled", d)
        delta_sigma_k = cfgx.number(delta_cfg, "sigma_k", d)
        delta_fallback_abs = cfgx.number(delta_cfg, "fallback_abs", d)
        delta_min_reference_samples = cfgx.integer(delta_cfg, "min_reference_samples", d)
        delta_action = _choice(cfgx.text(delta_cfg, "action", d).lower(), {"attention", "invalid"}, f"{d}.action")
        apply_statuses = _statuses(delta_cfg, "apply_statuses", d)
        reference_status = _choice(
            cfgx.text(delta_cfg, "reference_status", d).lower(), {"valid", "attention"}, f"{d}.reference_status"
        )
        delta_absolute_cfg = cfgx.section(delta_cfg, "absolute_range", d)
        delta_absolute_enabled = cfgx.flag(delta_absolute_cfg, "enabled", f"{d}.absolute_range")
        delta_absolute_min = cfgx.number(delta_absolute_cfg, "min", f"{d}.absolute_range")
        delta_absolute_max = cfgx.number(delta_absolute_cfg, "max", f"{d}.absolute_range")
        if delta_absolute_enabled and delta_absolute_max <= delta_absolute_min:
            raise cfgx.ConfigKeyError(f"config.yaml: '{d}.absolute_range' needs min < max")
        delta_absolute_apply_statuses = _statuses(delta_absolute_cfg, "apply_statuses", f"{d}.absolute_range")

        context.state["post_selection_qc_enabled"] = enabled
        context.state["post_selection_qc_mahalanobis_outlier_enabled"] = (
            mahalanobis_enabled
        )
        context.state["post_selection_qc_mahalanobis_distance_threshold"] = (
            mahalanobis_distance_threshold
        )
        context.state["post_selection_qc_min_reference_valid_samples"] = (
            min_reference_valid_samples
        )
        context.state["post_selection_qc_covariance_regularization"] = (
            covariance_regularization
        )

        if not enabled:
            context.state["post_selection_qc_invalidated_count"] = 0
            context.state["post_selection_qc_skipped"] = True
            context.state["post_selection_qc_skip_reason"] = "disabled_by_config"
            context.state["post_selection_qc_delta_outlier_flagged_count"] = 0
            return dict(selections)

        out: dict[str, SelectionResult] = dict(selections)

        # ---- Rule 1: E2g/A1g Mahalanobis invalidation (valid pool reference) ----
        valid_points: list[tuple[str, float, float]] = []
        for spectrum_id, selection in out.items():
            fit_status = str(selection.selected.params.get("fit_status", "valid")).strip().lower()
            if fit_status != "valid":
                continue
            e2g = _to_float(selection.selected.params.get("e2g_position"))
            a1g = _to_float(selection.selected.params.get("a1g_position"))
            if e2g is None or a1g is None or not np.isfinite(e2g) or not np.isfinite(a1g):
                continue
            valid_points.append((spectrum_id, float(e2g), float(a1g)))

        context.state["post_selection_qc_valid_pool_size"] = len(valid_points)
        context.state["post_selection_qc_reference_valid_pool_size"] = len(valid_points)
        invalidated = 0
        if not mahalanobis_enabled:
            context.state["post_selection_qc_invalidated_count"] = 0
            context.state["post_selection_qc_skipped"] = True
            context.state["post_selection_qc_skip_reason"] = "mahalanobis_disabled_by_config"
            context.state["post_selection_qc_center_e2g"] = float("nan")
            context.state["post_selection_qc_center_a1g"] = float("nan")
        elif len(valid_points) < min_reference_valid_samples:
            context.state["post_selection_qc_invalidated_count"] = 0
            context.state["post_selection_qc_skipped"] = True
            context.state["post_selection_qc_skip_reason"] = (
                "insufficient_reference_valid_samples"
            )
            context.state["post_selection_qc_center_e2g"] = float("nan")
            context.state["post_selection_qc_center_a1g"] = float("nan")
        else:
            coords = np.asarray([(e2g, a1g) for _, e2g, a1g in valid_points], dtype=float)
            center = np.median(coords, axis=0)
            centered = coords - center
            cov = np.matmul(centered.T, centered) / max(coords.shape[0] - 1, 1)
            cov = cov + (covariance_regularization * np.eye(2))
            inv_cov = np.linalg.pinv(cov)

            for spectrum_id, e2g, a1g in valid_points:
                diff = np.array([e2g, a1g], dtype=float) - center
                distance = float(np.sqrt(np.matmul(np.matmul(diff.T, inv_cov), diff)))
                if distance <= mahalanobis_distance_threshold:
                    continue

                selection = out[spectrum_id]
                params = dict(selection.selected.params)
                metrics = dict(selection.selected.metrics)

                invalid_reasons = _normalize_reason_list(params.get("invalid_reasons"))
                reason = "e2g_a1g_distance_outlier"
                if reason not in invalid_reasons:
                    invalid_reasons.append(reason)

                params["fit_status"] = "invalid"
                params["invalid_reasons"] = invalid_reasons
                metrics["is_valid_candidate"] = 0.0
                metrics["e2g_a1g_mahalanobis_distance"] = distance

                updated_fit = FitCandidate(
                    model_name=selection.selected.model_name,
                    params=params,
                    fitted_y=selection.selected.fitted_y,
                    metrics=metrics,
                )
                rationale = (
                    f"{selection.rationale};post_selection_qc=invalid_e2g_a1g_distance_outlier"
                    if selection.rationale
                    else "post_selection_qc=invalid_e2g_a1g_distance_outlier"
                )
                out[spectrum_id] = SelectionResult(selected=updated_fit, rationale=rationale)
                invalidated += 1

            context.state["post_selection_qc_skipped"] = False
            context.state["post_selection_qc_skip_reason"] = ""
            context.state["post_selection_qc_center_e2g"] = float(center[0])
            context.state["post_selection_qc_center_a1g"] = float(center[1])

        context.state["post_selection_qc_invalidated_count"] = invalidated

        # ---- Rule 2: Delta outlier vs dataset (typically set to attention) ----
        context.state["post_selection_qc_delta_outlier_enabled"] = delta_enabled
        context.state["post_selection_qc_delta_absolute_range_enabled"] = delta_absolute_enabled
        context.state["post_selection_qc_delta_absolute_range_min"] = float(delta_absolute_min)
        context.state["post_selection_qc_delta_absolute_range_max"] = float(delta_absolute_max)
        context.state["post_selection_qc_delta_absolute_range_apply_statuses"] = list(
            delta_absolute_apply_statuses
        )
        context.state["post_selection_qc_delta_outlier_sigma_k"] = float(delta_sigma_k)
        context.state["post_selection_qc_delta_outlier_fallback_abs"] = float(delta_fallback_abs)
        context.state["post_selection_qc_delta_outlier_action"] = delta_action
        context.state["post_selection_qc_delta_outlier_reference_status"] = reference_status
        context.state["post_selection_qc_delta_outlier_apply_statuses"] = list(apply_statuses)

        # 2-1) Absolute delta range cut first
        delta_absolute_invalidated_count = 0
        if delta_absolute_enabled:
            for spectrum_id, selection in out.items():
                params = dict(selection.selected.params)
                metrics = dict(selection.selected.metrics)
                fit_status = str(params.get("fit_status", "valid")).strip().lower()
                if fit_status not in delta_absolute_apply_statuses:
                    continue

                delta = _to_float(params.get("delta_e2g_a1g"))
                if delta is None or not np.isfinite(delta):
                    continue
                if delta_absolute_min <= float(delta) <= delta_absolute_max:
                    continue

                invalid_reasons = _normalize_reason_list(params.get("invalid_reasons"))
                reason = "delta_out_of_target_range"
                if reason not in invalid_reasons:
                    invalid_reasons.append(reason)

                params["fit_status"] = "invalid"
                params["invalid_reasons"] = invalid_reasons
                metrics["is_valid_candidate"] = 0.0
                metrics["delta_absolute_range_min"] = float(delta_absolute_min)
                metrics["delta_absolute_range_max"] = float(delta_absolute_max)

                updated_fit = FitCandidate(
                    model_name=selection.selected.model_name,
                    params=params,
                    fitted_y=selection.selected.fitted_y,
                    metrics=metrics,
                )
                rationale = (
                    f"{selection.rationale};post_selection_qc=delta_out_of_target_range"
                    if selection.rationale
                    else "post_selection_qc=delta_out_of_target_range"
                )
                out[spectrum_id] = SelectionResult(selected=updated_fit, rationale=rationale)
                delta_absolute_invalidated_count += 1
        context.state["post_selection_qc_delta_absolute_invalidated_count"] = (
            delta_absolute_invalidated_count
        )

        delta_reference_points: list[tuple[str, float]] = []
        for spectrum_id, selection in out.items():
            fit_status = str(selection.selected.params.get("fit_status", "valid")).strip().lower()
            if fit_status != reference_status:
                continue
            delta = _to_float(selection.selected.params.get("delta_e2g_a1g"))
            if delta is None or not np.isfinite(delta):
                continue
            delta_reference_points.append((spectrum_id, float(delta)))

        context.state["post_selection_qc_delta_reference_pool_size"] = len(delta_reference_points)
        delta_outlier_flagged_count = 0
        if not delta_enabled:
            context.state["post_selection_qc_delta_outlier_skipped"] = True
            context.state["post_selection_qc_delta_outlier_skip_reason"] = "disabled_by_config"
        elif len(delta_reference_points) < delta_min_reference_samples:
            context.state["post_selection_qc_delta_outlier_skipped"] = True
            context.state["post_selection_qc_delta_outlier_skip_reason"] = (
                "insufficient_reference_samples"
            )
        else:
            values = np.asarray([v for _, v in delta_reference_points], dtype=float)
            delta_med, delta_sigma = _mad_sigma(values)
            if delta_sigma > 1.0e-12:
                threshold = max(delta_fallback_abs, delta_sigma_k * delta_sigma)
            else:
                threshold = delta_fallback_abs

            for spectrum_id, selection in out.items():
                params = dict(selection.selected.params)
                metrics = dict(selection.selected.metrics)
                fit_status = str(params.get("fit_status", "valid")).strip().lower()
                if fit_status not in apply_statuses:
                    continue

                delta = _to_float(params.get("delta_e2g_a1g"))
                if delta is None or not np.isfinite(delta):
                    continue

                abs_dev = abs(float(delta) - float(delta_med))
                if abs_dev <= threshold:
                    continue

                invalid_reasons = _normalize_reason_list(params.get("invalid_reasons"))
                attention_reasons = _normalize_reason_list(params.get("attention_reasons"))
                reason = "delta_outlier_vs_dataset"

                if delta_action == "invalid":
                    if reason not in invalid_reasons:
                        invalid_reasons.append(reason)
                    params["fit_status"] = "invalid"
                    params["invalid_reasons"] = invalid_reasons
                    metrics["is_valid_candidate"] = 0.0
                else:
                    if reason not in attention_reasons:
                        attention_reasons.append(reason)
                    if fit_status == "valid":
                        params["fit_status"] = "attention"
                    params["attention_reasons"] = attention_reasons

                metrics["delta_outlier_abs_deviation"] = float(abs_dev)
                metrics["delta_outlier_threshold"] = float(threshold)
                metrics["delta_outlier_reference_median"] = float(delta_med)

                updated_fit = FitCandidate(
                    model_name=selection.selected.model_name,
                    params=params,
                    fitted_y=selection.selected.fitted_y,
                    metrics=metrics,
                )
                rationale = (
                    f"{selection.rationale};post_selection_qc=delta_outlier_vs_dataset"
                    if selection.rationale
                    else "post_selection_qc=delta_outlier_vs_dataset"
                )
                out[spectrum_id] = SelectionResult(selected=updated_fit, rationale=rationale)
                delta_outlier_flagged_count += 1

            context.state["post_selection_qc_delta_outlier_skipped"] = False
            context.state["post_selection_qc_delta_outlier_skip_reason"] = ""
            context.state["post_selection_qc_delta_outlier_median"] = float(delta_med)
            context.state["post_selection_qc_delta_outlier_sigma"] = float(delta_sigma)
            context.state["post_selection_qc_delta_outlier_threshold"] = float(threshold)

        context.state["post_selection_qc_delta_outlier_flagged_count"] = delta_outlier_flagged_count
        return out
