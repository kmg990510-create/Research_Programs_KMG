"""Manual override storage and projection helpers."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
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
) -> Path:
    override_path = override_path_for_report(report_json)
    override_path.parent.mkdir(parents=True, exist_ok=True)

    payload = _load_override_doc(override_path)
    item = {
        "spectrum_id": str(spectrum_id),
        "action_type": str(action_type),
        "selected_model": str(selected_model),
        "params": dict(params) if isinstance(params, Mapping) else {},
        "metrics": dict(metrics) if isinstance(metrics, Mapping) else {},
        "fitted_y": list(fitted_y) if isinstance(fitted_y, list) else [],
        "operator_note": str(operator_note or ""),
        "updated_at_utc": now_utc_iso(),
    }
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
    latest: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        spectrum_id = str(item.get("spectrum_id", "")).strip()
        if not spectrum_id:
            continue
        current = latest.get(spectrum_id)
        if current is None:
            latest[spectrum_id] = item
            continue
        if _updated_rank(item.get("updated_at_utc")) >= _updated_rank(current.get("updated_at_utc")):
            latest[spectrum_id] = item
    return latest


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

        selected_model = str(item.get("selected_model", "")).strip()
        if selected_model:
            row["selected_model"] = selected_model

        params = item.get("params")
        if isinstance(params, dict):
            row.update(params)
            row["fit_params"] = dict(params)

        metrics = item.get("metrics")
        if isinstance(metrics, dict):
            row.update(metrics)
            row["fit_metrics"] = dict(metrics)

        fitted_y = item.get("fitted_y")
        if isinstance(fitted_y, list):
            row["fitted_y"] = fitted_y

        row["manual_override"] = True
        row["manual_override_action"] = str(item.get("action_type", "manual_refit"))
        row["manual_override_updated_at"] = str(item.get("updated_at_utc", ""))

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

