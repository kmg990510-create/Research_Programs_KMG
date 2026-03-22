"""Shared request/response contract for Streamlit <-> desktop manual refit flow."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUEST_SCHEMA_VERSION = "manual_refit_request.v1"
RESPONSE_SCHEMA_VERSION = "manual_refit_response.v1"

PEAK_ORDER = ("pl", "lo", "e2g", "a1g", "zo", "la")


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _default_fraction_for_row(row: dict[str, Any]) -> float:
    profile = str(row.get("line_profile", "pvoigt") or "pvoigt").strip().lower()
    if profile not in {"gaussian", "lorentz", "pvoigt"}:
        model_name = str(row.get("selected_model", "") or "").strip().lower()
        if "gaussian" in model_name:
            profile = "gaussian"
        elif "lorentz" in model_name:
            profile = "lorentz"
        else:
            profile = "pvoigt"
    if profile == "gaussian":
        return 0.0
    if profile == "lorentz":
        return 1.0
    return 0.5


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    item_attr = getattr(value, "item", None)
    if callable(item_attr):
        try:
            return item_attr()
        except Exception:
            pass
    return str(value)


def extract_peak_rows_from_row(row: dict[str, Any]) -> list[dict[str, Any]]:
    peaks: list[dict[str, Any]] = []
    default_fraction = _default_fraction_for_row(row)
    for peak in PEAK_ORDER:
        center = _to_float(row.get(f"{peak}_position"))
        if center is None:
            continue
        fraction = _to_float(row.get(f"{peak}_fraction"))
        peaks.append(
            {
                "peak": peak,
                "center": center,
                "height": _to_float(row.get(f"{peak}_height")),
                "fwhm": _to_float(row.get(f"{peak}_fwhm")),
                "fraction": float(default_fraction if fraction is None else max(0.0, min(1.0, fraction))),
                "fixed_fraction": False,
                "fixed_center": False,
                "fixed_height": False,
                "fixed_fwhm": False,
            }
        )
    return peaks


def build_editor_request(
    *,
    report_path: Path,
    spectrum_id: str,
    modality: str,
    source_file: str,
    selected_model: str,
    calibration_offset: float = 0.0,
    row_snapshot: dict[str, Any],
    x: list[float],
    y: list[float],
) -> dict[str, Any]:
    return {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "report_path": str(report_path),
        "spectrum_id": spectrum_id,
        "modality": modality,
        "source_file": source_file,
        "selected_model": selected_model,
        "calibration_offset": float(calibration_offset),
        "row_snapshot": _json_safe(row_snapshot),
        "x": x,
        "y": y,
        "peaks": extract_peak_rows_from_row(row_snapshot),
    }


def validate_editor_response(payload: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "response must be a JSON object"
    if str(payload.get("schema_version", "")).strip() != RESPONSE_SCHEMA_VERSION:
        return False, "unsupported schema_version"
    if not str(payload.get("spectrum_id", "")).strip():
        return False, "missing spectrum_id"
    if not str(payload.get("selected_model", "")).strip():
        return False, "missing selected_model"
    if not isinstance(payload.get("peaks"), list):
        return False, "missing peaks array"
    return True, ""
