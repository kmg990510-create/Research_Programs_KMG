"""What a person changed after the automatic analysis.

A ``ReviewState`` is stored next to the results as ``review.json``. The raw
files and the automatic results are never modified: geometry, method options,
decisions and group names are kept here and applied on top.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from fet_core.model import DeviceGeometry

SCHEMA_VERSION = "fet_review.v1"

DECISION_AUTO = "auto"  # follow the automatic status
DECISION_APPROVED = "approved"
DECISION_REJECTED = "rejected"  # kept in the tables, left out of statistics
DECISIONS = (DECISION_AUTO, DECISION_APPROVED, DECISION_REJECTED)

GEOMETRY_FIELDS = ("W_um", "L_um", "t_ox_nm", "eps_r")


def run_key(source_file: str, run_id: str) -> str:
    return f"{source_file}|{run_id}"


def sweep_key(source_file: str, run_id: str, sweep: str) -> str:
    return f"{source_file}|{run_id}|{sweep}"


@dataclass
class ReviewState:
    # Batch-wide values that replace config.yaml for this batch (None = use config.yaml).
    geometry: dict[str, float] | None = None
    vth_subtract_half_vds: bool | None = None
    vth_const_current_nA_per_um: float | None = None
    # run_key -> geometry of that device
    geometry_overrides: dict[str, dict[str, float]] = field(default_factory=dict)
    # sweep_key -> decision / note
    decisions: dict[str, str] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)
    # group name from the file -> name to show; display names in plotting order
    group_names: dict[str, str] = field(default_factory=dict)
    group_order: list[str] = field(default_factory=list)

    def decision(self, source_file: str, run_id: str, sweep: str) -> str:
        return self.decisions.get(sweep_key(source_file, run_id, sweep), DECISION_AUTO)

    def set_decision(self, source_file: str, run_id: str, sweep: str, decision: str, note: str | None = None) -> None:
        if decision not in DECISIONS:
            raise ValueError(f"unknown decision: {decision}")
        key = sweep_key(source_file, run_id, sweep)
        if decision == DECISION_AUTO:
            self.decisions.pop(key, None)
        else:
            self.decisions[key] = decision
        if note is not None:
            if note.strip():
                self.notes[key] = note.strip()
            else:
                self.notes.pop(key, None)

    def display_group(self, group: str) -> str:
        return self.group_names.get(group, group) or group

    def device_geometry(self, source_file: str, run_id: str) -> DeviceGeometry | None:
        values = self.geometry_overrides.get(run_key(source_file, run_id))
        return DeviceGeometry(**values) if values else None

    def analysis_inputs(self) -> dict[str, Any]:
        """The part of the review that changes the analysis itself (not the decisions)."""
        return {
            "geometry": self.geometry,
            "vth_subtract_half_vds": self.vth_subtract_half_vds,
            "vth_const_current_nA_per_um": self.vth_const_current_nA_per_um,
            "geometry_overrides": self.geometry_overrides,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReviewState":
        known = {name for name in cls.__dataclass_fields__}
        return cls(**{key: value for key, value in payload.items() if key in known})


def load_review(path: Path) -> ReviewState:
    """The stored review, or an empty one when the file does not exist."""
    if not path.exists():
        return ReviewState()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"review file is not a JSON object: {path}")
    return ReviewState.from_dict(payload)


def save_review(path: Path, review: ReviewState) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(review.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
