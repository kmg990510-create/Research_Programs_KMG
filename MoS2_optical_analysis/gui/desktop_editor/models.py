"""Dataclasses for desktop editor request/response models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from gui.components.manual_refit_contract import RESPONSE_SCHEMA_VERSION


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(slots=True)
class PeakRow:
    peak: str
    center: float
    height: float
    fwhm: float
    fraction: float = 0.5
    fixed_fraction: bool = False
    fixed_center: bool = False
    fixed_height: bool = False
    fixed_fwhm: bool = False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "PeakRow":
        return cls(
            peak=str(payload.get("peak", "")).strip().lower(),
            center=_to_float(payload.get("center"), 0.0),
            height=max(_to_float(payload.get("height"), 0.0), 0.0),
            fwhm=max(_to_float(payload.get("fwhm"), 1.0), 1.0e-6),
            fraction=float(min(max(_to_float(payload.get("fraction"), 0.5), 0.0), 1.0)),
            fixed_fraction=bool(payload.get("fixed_fraction", False)),
            fixed_center=bool(payload.get("fixed_center", False)),
            fixed_height=bool(payload.get("fixed_height", False)),
            fixed_fwhm=bool(payload.get("fixed_fwhm", False)),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "peak": self.peak,
            "center": float(self.center),
            "height": float(self.height),
            "fwhm": float(self.fwhm),
            "fraction": float(min(max(self.fraction, 0.0), 1.0)),
            "fixed_fraction": bool(self.fixed_fraction),
            "fixed_center": bool(self.fixed_center),
            "fixed_height": bool(self.fixed_height),
            "fixed_fwhm": bool(self.fixed_fwhm),
        }


@dataclass(slots=True)
class EditorRequest:
    schema_version: str
    spectrum_id: str
    modality: str
    source_file: str
    report_path: str
    selected_model: str
    calibration_offset: float = 0.0
    x: list[float] = field(default_factory=list)
    y: list[float] = field(default_factory=list)
    peaks: list[PeakRow] = field(default_factory=list)
    row_snapshot: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "EditorRequest":
        peaks_raw = payload.get("peaks", [])
        peaks = [
            PeakRow.from_payload(item)
            for item in peaks_raw
            if isinstance(item, Mapping)
        ]
        return cls(
            schema_version=str(payload.get("schema_version", "")),
            spectrum_id=str(payload.get("spectrum_id", "")).strip(),
            modality=str(payload.get("modality", "raman")).strip().lower() or "raman",
            source_file=str(payload.get("source_file", "")).strip(),
            report_path=str(payload.get("report_path", "")).strip(),
            selected_model=str(payload.get("selected_model", "")).strip(),
            calibration_offset=_to_float(payload.get("calibration_offset"), 0.0),
            x=[float(v) for v in payload.get("x", [])] if isinstance(payload.get("x"), list) else [],
            y=[float(v) for v in payload.get("y", [])] if isinstance(payload.get("y"), list) else [],
            peaks=peaks,
            row_snapshot=dict(payload.get("row_snapshot", {}))
            if isinstance(payload.get("row_snapshot"), Mapping)
            else {},
        )


@dataclass(slots=True)
class EditorResponse:
    spectrum_id: str
    modality: str
    selected_model: str
    peaks: list[PeakRow]
    reason: str = "manual_refit_from_desktop"
    operator_note: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "spectrum_id": self.spectrum_id,
            "modality": self.modality,
            "selected_model": self.selected_model,
            "reason": self.reason,
            "operator_note": self.operator_note,
            "peaks": [peak.to_payload() for peak in self.peaks],
        }
