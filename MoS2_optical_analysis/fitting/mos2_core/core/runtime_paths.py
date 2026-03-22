"""Runtime path helpers that work for both source and frozen execution."""

from __future__ import annotations

import sys
from pathlib import Path


def runtime_project_root(reference_file: str | Path, parents_up: int) -> Path:
    """
    Resolve project/workspace root.

    - Source run: derive from `reference_file`.
    - Frozen run: use executable directory so user data stays external.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(reference_file).resolve().parents[parents_up]
