"""Manual override storage and projection helpers."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any, Mapping


REPORT_SUFFIX = "_fit_report.json"
CSV_SUFFIX = "_fit_parameters.csv"
OVERRIDE_SUFFIX = "_manual_overrides.json"


def run_id_from_report_path(report_json: Path) -> str:
    name = report_json.name
    if name.endswith(REPORT_SUFFIX):
        return name[: -len(REPORT_SUFFIX)]
    return report_json.stem


def override_path_for_report(report_json: Path) -> Path:
    modality_root = report_json.parent.parent
    run_id = run_id_from_report_path(report_json)
    return modality_root / "manual_refits" / f"{run_id}{OVERRIDE_SUFFIX}"


def override_mtime_ns_for_report(report_json: Path) -> int:
    path = override_path_for_report(report_json)
    if not path.exists():
        return 0
    return int(path.stat().st_mtime_ns)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_override_doc(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": "manual_overrides.v1", "report_json": "", "updated_at_utc": now_utc_iso(), "items": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid manual override payload type: {type(payload)}")
    if not isinstance(payload.get("items"), list):
        payload["items"] = []
    return payload


def upsert_manual_override(
    *,
    report_json: Path,
    spectrum_id: str,
    action_type: str,
    selected_model: str,
    params: Mapping[str, Any] | None = None,
    metrics: Mapping[str, Any] | None = None,
    fitted_y: list[float] | None = None,
    operator_note: str = "",
    review_decision: str | None = None,
) -> Path:
    override_path = override_path_for_report(report_json)
    override_path.parent.mkdir(parents=True, exist_ok=True)

    payload = _load_override_doc(override_path)
    item: dict[str, Any] = {
        "spectrum_id": str(spectrum_id),
        "action_type": str(action_type),
        "selected_model": str(selected_model),
        "params": dict(params) if isinstance(params, Mapping) else {},
        "metrics": dict(metrics) if isinstance(metrics, Mapping) else {},
        "fitted_y": list(fitted_y) if isinstance(fitted_y, list) else [],
        "operator_note": str(operator_note or ""),
        "updated_at_utc": now_utc_iso(),
    }
    if review_decision is not None and str(review_decision).strip():
        item["review_decision"] = str(review_decision).strip()
    payload.setdefault("schema_version", "manual_overrides.v1")
    payload["report_json"] = str(report_json)
    payload["updated_at_utc"] = item["updated_at_utc"]
    payload["items"].append(item)
    override_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return override_path


def _updated_rank(value: Any) -> tuple[int, str]:
    text = str(value or "").strip()
    if not text:
        return (0, "")
    return (1, text)


def _latest_items_by_spectrum(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    ordered = [item for item in items if isinstance(item, dict) and str(item.get("spectrum_id", "")).strip()]
    ordered.sort(key=lambda item: _updated_rank(item.get("updated_at_utc")))
    latest: dict[str, dict[str, Any]] = {}
    for item in ordered:
        spectrum_id = str(item.get("spectrum_id", "")).strip()
        current = latest.get(spectrum_id)
        if current is None:
            latest[spectrum_id] = deepcopy(item)
            continue
        merged = deepcopy(current)
        if str(item.get("selected_model", "")).strip():
            merged["selected_model"] = str(item.get("selected_model", "")).strip()
        item_params = item.get("params")
        if isinstance(item_params, dict) and item_params:
            if str(item.get("action_type", "")) in {"manual_refit", "model_override"}:
                merged["params"] = dict(item_params)
            else:
                base_params = dict(merged.get("params") or {})
                base_params.update(item_params)
                merged["params"] = base_params
        item_metrics = item.get("metrics")
        if isinstance(item_metrics, dict) and item_metrics:
            if str(item.get("action_type", "")) in {"manual_refit", "model_override"}:
                merged["metrics"] = dict(item_metrics)
            else:
                base_metrics = dict(merged.get("metrics") or {})
                base_metrics.update(item_metrics)
                merged["metrics"] = base_metrics
        item_fitted_y = item.get("fitted_y")
        if isinstance(item_fitted_y, list) and item_fitted_y:
            merged["fitted_y"] = list(item_fitted_y)
        if str(item.get("review_decision", "")).strip():
            merged["review_decision"] = str(item["review_decision"]).strip()
        if str(item.get("action_type", "")).strip():
            merged["action_type"] = str(item["action_type"]).strip()
        if str(item.get("operator_note", "")).strip():
            merged["operator_note"] = str(item["operator_note"]).strip()
        if str(item.get("updated_at_utc", "")).strip():
            merged["updated_at_utc"] = str(item["updated_at_utc"]).strip()
        latest[spectrum_id] = merged
    return latest


def _finite_float(value: Any) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


def _recompute_derived_row_fields(row: dict[str, Any], action_type: str, params: dict[str, Any]) -> None:
    fit_params = row.get("fit_params") if isinstance(row.get("fit_params"), dict) else {}

    e2g_pos = _finite_float(row.get("e2g_position"))
    a1g_pos = _finite_float(row.get("a1g_position"))
    if e2g_pos is not None and a1g_pos is not None and ("e2g_position" in params or "a1g_position" in params):
        delta = float(a1g_pos - e2g_pos)
        row["delta_e2g_a1g"] = delta
        fit_params["delta_e2g_a1g"] = delta

    a_minus_pos = _finite_float(row.get("a_minus_position"))
    a0_pos = _finite_float(row.get("a0_position"))
    if a_minus_pos is not None and a0_pos is not None and ("a_minus_position" in params or "a0_position" in params):
        split = float(a0_pos - a_minus_pos)
        row["a_minus_a0_energy_split"] = split
        fit_params["a_minus_a0_energy_split"] = split

    if action_type == "manual_refit" and "fit_status" not in params:
        row["fit_status"] = "valid"
        row["invalid_reasons"] = []
        row["attention_reasons"] = []
        row["quality_flags"] = []
        row["needs_attention"] = False
        row["attention_score"] = 0
        fit_params["fit_status"] = "valid"
        fit_params["invalid_reasons"] = []
        fit_params["attention_reasons"] = []
    elif action_type in {"model_override", "manual_refit"} and "fit_status" in params:
        status = str(row.get("fit_status", "valid")).strip().lower() or "valid"
        inv = row.get("invalid_reasons") if isinstance(row.get("invalid_reasons"), list) else []
        att = row.get("attention_reasons") if isinstance(row.get("attention_reasons"), list) else []
        qflags = list(dict.fromkeys([str(x) for x in inv + att if str(x).strip()]))
        row["quality_flags"] = qflags
        row["needs_attention"] = status in {"attention", "invalid"} or bool(qflags)
        row["attention_score"] = len(qflags)

    if fit_params:
        row["fit_params"] = fit_params


def _recompute_payload_summaries(projected: dict[str, Any], spectra: list[Any]) -> None:
    rows = [r for r in spectra if isinstance(r, dict)]
    if not rows:
        return

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    accepted_count = 0
    flagged_count = 0
    decisions_count = 0
    parameters_count = 0
    attention_count = 0
    invalid_count = 0

    for row in rows:
        status = str(row.get("fit_status", "valid")).strip().lower() or "valid"
        decision = str(row.get("review_decision", "auto")).strip().lower() or "auto"
        reviewed = bool(row.get("reviewed", False)) or decision != "auto"
        needs_att = bool(row.get("needs_attention", False))

        if reviewed:
            decisions_count += 1

        if decision == "rejected":
            continue

        accepted_count += 1
        if status == "invalid":
            invalid_count += 1
        if needs_att:
            attention_count += 1

        if (needs_att or status != "valid") and decision not in {"approved", "accepted", "refit"}:
            flagged_count += 1

        if status != "invalid":
            parameters_count += 1
            map_id = str(row.get("map_id") or "default_map")
            grouped[map_id].append(row)

    map_summaries: list[dict[str, Any]] = []
    for _map_id, items in grouped.items():
        def _mean_col(col: str) -> float | None:
            vals = [v for v in (_finite_float(item.get(col)) for item in items) if v is not None]
            return float(mean(vals)) if vals else None

        summary: dict[str, Any] = {
            "n_spectra": len(items),
            "mean_peak_position": _mean_col("peak_position"),
            "mean_peak_amplitude": _mean_col("peak_amplitude"),
            "mean_e2g_position": _mean_col("e2g_position"),
            "mean_a1g_position": _mean_col("a1g_position"),
            "mean_delta_e2g_a1g": _mean_col("delta_e2g_a1g"),
        }
        for pl_col in ("pl_position", "a0_position", "a_minus_position", "a_minus_a0_area_ratio"):
            val = _mean_col(pl_col)
            if val is not None:
                summary[f"mean_{pl_col}"] = val
        map_summaries.append(summary)

    base_counts = projected.get("counts") if isinstance(projected.get("counts"), dict) else {}
    projected["counts"] = {
        "qc_total": max(int(_finite_float(base_counts.get("qc_total")) or len(rows)), len(rows)),
        "flagged": flagged_count,
        "decisions": decisions_count,
        "accepted": accepted_count,
        "parameters": parameters_count,
        "maps": len(map_summaries),
    }
    projected["attention_count"] = attention_count
    projected["invalid_count"] = invalid_count
    base_failures = int(_finite_float(projected.get("fit_failure_count")) or 0)
    projected["fit_failure_count"] = min(base_failures, invalid_count) if base_failures > 0 else invalid_count
    projected["map_summary"] = map_summaries


def apply_manual_overrides_to_payload(payload: Mapping[str, Any], report_json: Path) -> dict[str, Any]:
    """Return payload with latest manual overrides projected onto spectra rows."""
    projected = deepcopy(dict(payload))
    spectra = projected.get("spectra")
    if not isinstance(spectra, list) or not spectra:
        return projected

    override_path = override_path_for_report(report_json)
    if not override_path.exists():
        return projected

    override_doc = _load_override_doc(override_path)
    items = override_doc.get("items", [])
    if not isinstance(items, list) or not items:
        return projected

    latest_by_spectrum = _latest_items_by_spectrum(items)
    if not latest_by_spectrum:
        return projected

    for row in spectra:
        if not isinstance(row, dict):
            continue
        spectrum_id = str(row.get("spectrum_id", "")).strip()
        item = latest_by_spectrum.get(spectrum_id)
        if item is None:
            continue

        action_type = str(item.get("action_type", "manual_refit"))
        selected_model = str(item.get("selected_model", "")).strip()
        if selected_model:
            row["selected_model"] = selected_model

        params = item.get("params")
        params_dict = dict(params) if isinstance(params, dict) else {}
        if params_dict:
            row.update(params_dict)
            if action_type in {"manual_refit", "model_override"}:
                row["fit_params"] = dict(params_dict)
            elif isinstance(row.get("fit_params"), dict):
                merged_fp = dict(row["fit_params"])
                merged_fp.update(params_dict)
                row["fit_params"] = merged_fp
            else:
                row["fit_params"] = dict(params_dict)

        metrics = item.get("metrics")
        if isinstance(metrics, dict) and metrics:
            row.update(metrics)
            if action_type in {"manual_refit", "model_override"}:
                row["fit_metrics"] = dict(metrics)
            elif isinstance(row.get("fit_metrics"), dict):
                merged_fm = dict(row["fit_metrics"])
                merged_fm.update(metrics)
                row["fit_metrics"] = merged_fm
            else:
                row["fit_metrics"] = dict(metrics)

        fitted_y = item.get("fitted_y")
        if isinstance(fitted_y, list) and fitted_y:
            row["fitted_y"] = fitted_y

        review_decision = str(item.get("review_decision", "")).strip()
        if review_decision:
            row["review_decision"] = review_decision
            row["reviewed"] = review_decision != "auto"

        _recompute_derived_row_fields(row, action_type=action_type, params=params_dict)

        row["manual_override"] = True
        row["manual_override_action"] = action_type
        row["manual_override_updated_at"] = str(item.get("updated_at_utc", ""))

    _recompute_payload_summaries(projected, spectra)
    return projected


def result_relpaths_linked_to_report_json(relative_report_json: str) -> list[str]:
    """Return linked result-relative paths for report-json set operations."""
    rel = Path(relative_report_json).as_posix().strip()
    if not rel.startswith("reports/") or not rel.endswith(REPORT_SUFFIX):
        return [rel]
    run_id = Path(rel).name[: -len(REPORT_SUFFIX)]
    return [
        rel,
        f"reports/{run_id}{CSV_SUFFIX}",
        f"manual_refits/{run_id}{OVERRIDE_SUFFIX}",
    ]


def is_result_json_selectable(relative_path: str | Path) -> bool:
    rel = Path(relative_path).as_posix().strip()
    if rel.startswith("reports/") and rel.endswith(REPORT_SUFFIX):
        return True
    if rel.startswith("manual_refits/") and rel.endswith(OVERRIDE_SUFFIX):
        return True
    return False

