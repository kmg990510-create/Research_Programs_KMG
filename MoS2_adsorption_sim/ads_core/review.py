"""Human review state stored next to simulation results as ``review.json``.

Simulation outputs are never overwritten by review actions. Decisions
(``auto`` / ``approved`` / ``rejected``), per-pose notes, and group display
names/ordering are stored here and applied when building tables and exports.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "ads_review.v1"

DECISION_AUTO = "auto"  # follow automatic quality status
DECISION_APPROVED = "approved"
DECISION_REJECTED = "rejected"  # kept in tables, excluded from summaries and exports
DECISIONS = (DECISION_AUTO, DECISION_APPROVED, DECISION_REJECTED)


def make_group_key(surface_id: str, molecule_id: str, calculator_id: str) -> str:
    return f"{surface_id} | {molecule_id} | {calculator_id}"


@dataclass
class ReviewState:
    decisions: dict[str, str] = field(default_factory=dict)  # pose_id -> decision
    notes: dict[str, str] = field(default_factory=dict)  # pose_id -> note
    group_names: dict[str, str] = field(default_factory=dict)  # group_key -> display name
    group_order: list[str] = field(default_factory=list)  # display names in plotting order

    def decision(self, pose_id: str) -> str:
        return self.decisions.get(pose_id, DECISION_AUTO)

    def note(self, pose_id: str) -> str:
        return self.notes.get(pose_id, "")

    def set_decision(self, pose_id: str, decision: str, note: str | None = None) -> None:
        if decision not in DECISIONS:
            raise ValueError(f"Unknown decision {decision!r}; expected one of {DECISIONS}")
        if decision == DECISION_AUTO:
            self.decisions.pop(pose_id, None)
        else:
            self.decisions[pose_id] = decision
        if note is not None:
            if note.strip():
                self.notes[pose_id] = note.strip()
            else:
                self.notes.pop(pose_id, None)

    def display_group(self, group_key: str) -> str:
        return self.group_names.get(group_key, group_key) or group_key

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReviewState":
        known = {name for name in cls.__dataclass_fields__}
        return cls(**{key: value for key, value in payload.items() if key in known})


def load_review(path: Path) -> ReviewState:
    """Load stored review, or return an empty ``ReviewState`` when missing."""
    if not path.exists():
        return ReviewState()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Review file is not a JSON object: {path}")
    return ReviewState.from_dict(payload)


def save_review(path: Path, review: ReviewState) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(review.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
