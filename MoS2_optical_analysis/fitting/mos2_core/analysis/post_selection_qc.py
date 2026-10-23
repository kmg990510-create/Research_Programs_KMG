"""Post-selection QC rules applied before confidence/review stages."""

from __future__ import annotations

from typing import Mapping

import numpy as np

from ..core.interfaces import PostSelectionQCStage
from ..core.types import FitCandidate, PipelineContext, SelectionResult


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


class MahalanobisPostSelectionQC(PostSelectionQCStage):
    """
    Invalidate geometrically implausible E2g/A1g locations using Mahalanobis distance.

    Reference distribution is built from currently selected valid spectra only.
    """

    def __init__(
        self,
        mahalanobis_distance_threshold: float = 3.0,
        min_reference_valid_samples: int = 30,
        covariance_regularization: float = 1.0e-6,
    ) -> None:
        self.mahalanobis_distance_threshold = float(mahalanobis_distance_threshold)
        self.min_reference_valid_samples = int(min_reference_valid_samples)
        self.covariance_regularization = float(covariance_regularization)

    def run(
        self,
        selections: Mapping[str, SelectionResult],
        context: PipelineContext,
    ) -> Mapping[str, SelectionResult]:
        raman_cfg = context.config.get("raman", {}) if isinstance(context.config, dict) else {}
        qc_cfg = (
            raman_cfg.get("post_selection_qc", {})
            if isinstance(raman_cfg, dict)
            else {}
        )
        mahalanobis_cfg = (
            qc_cfg.get("mahalanobis_outlier", {})
            if isinstance(qc_cfg, dict)
            else {}
        )

        enabled = bool(qc_cfg.get("enabled", True))
        mahalanobis_enabled = bool(
            mahalanobis_cfg.get("enabled", True)
            if isinstance(mahalanobis_cfg, dict)
            else True
        )
        mahalanobis_distance_threshold = float(
            qc_cfg.get(
                "mahalanobis_distance_threshold",
                self.mahalanobis_distance_threshold,
            )
        )
        min_reference_valid_samples = int(
            qc_cfg.get(
                "min_reference_valid_samples",
                self.min_reference_valid_samples,
            )
        )
        covariance_regularization = float(
            qc_cfg.get(
                "covariance_regularization",
                self.covariance_regularization,
            )
        )

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
        delta_cfg = qc_cfg.get("delta_outlier", {}) if isinstance(qc_cfg, dict) else {}
        delta_enabled = bool(delta_cfg.get("enabled", True))
        delta_sigma_k = float(delta_cfg.get("sigma_k", 6.0))
        delta_fallback_abs = float(delta_cfg.get("fallback_abs", 3.0))
        delta_absolute_cfg = (
            delta_cfg.get("absolute_range", {})
            if isinstance(delta_cfg, dict)
            else {}
        )
        delta_absolute_enabled = bool(
            delta_absolute_cfg.get("enabled", True)
            if isinstance(delta_absolute_cfg, dict)
            else True
        )
        delta_absolute_min = float(
            delta_absolute_cfg.get("min", 17.0)
            if isinstance(delta_absolute_cfg, dict)
            else 17.0
        )
        delta_absolute_max = float(
            delta_absolute_cfg.get("max", 25.0)
            if isinstance(delta_absolute_cfg, dict)
            else 25.0
        )
        if delta_absolute_max <= delta_absolute_min:
            delta_absolute_enabled = False
        absolute_apply_raw = (
            delta_absolute_cfg.get("apply_statuses", ["valid", "attention"])
            if isinstance(delta_absolute_cfg, dict)
            else ["valid", "attention"]
        )
        if isinstance(absolute_apply_raw, list):
            delta_absolute_apply_statuses = [
                str(v).strip().lower()
                for v in absolute_apply_raw
                if str(v).strip().lower() in {"valid", "attention"}
            ]
        else:
            delta_absolute_apply_statuses = ["valid", "attention"]
        if not delta_absolute_apply_statuses:
            delta_absolute_apply_statuses = ["valid", "attention"]
        delta_min_reference_samples = int(
            delta_cfg.get("min_reference_samples", min_reference_valid_samples)
        )
        delta_action = str(delta_cfg.get("action", "attention")).strip().lower()
        if delta_action not in {"attention", "invalid"}:
            delta_action = "attention"

        apply_statuses_raw = delta_cfg.get("apply_statuses", ["valid"])
        if isinstance(apply_statuses_raw, list):
            apply_statuses = [
                str(v).strip().lower()
                for v in apply_statuses_raw
                if str(v).strip().lower() in {"valid", "attention"}
            ]
        else:
            apply_statuses = ["valid"]
        if not apply_statuses:
            apply_statuses = ["valid"]

        reference_status = str(delta_cfg.get("reference_status", "valid")).strip().lower()
        if reference_status not in {"valid", "attention"}:
            reference_status = "valid"

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
