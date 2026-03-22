"""Persistent storage for reviewer decisions and approvals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from ..core.types import ReviewDecision


class DecisionStore:
    """JSONL-backed decision storage used by the review app."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, decision: ReviewDecision) -> None:
        payload = {
            "spectrum_id": decision.spectrum_id,
            "decision": decision.decision,
            "reviewer_id": decision.reviewer_id,
            "notes": decision.notes,
            "overrides": dict(decision.overrides),
        }
        with self.path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload) + "\n")

    def append_many(self, decisions: Iterable[ReviewDecision]) -> None:
        for decision in decisions:
            self.append(decision)

    def load_all(self) -> list[ReviewDecision]:
        if not self.path.exists():
            return []
        decisions: list[ReviewDecision] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            decisions.append(
                ReviewDecision(
                    spectrum_id=item["spectrum_id"],
                    decision=item["decision"],
                    reviewer_id=item.get("reviewer_id"),
                    notes=item.get("notes", ""),
                    overrides=item.get("overrides", {}),
                )
            )
        return decisions
