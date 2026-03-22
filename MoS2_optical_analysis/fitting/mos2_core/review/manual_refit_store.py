"""Persistent JSONL store for manual refit records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


class ManualRefitStore:
    """JSONL-backed append-only store for manual refit records."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")

    def append_many(self, records: Iterable[dict[str, Any]]) -> None:
        for record in records:
            self.append(record)

    def load_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            out.append(json.loads(line))
        return out

