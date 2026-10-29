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


def runtime_resource_root() -> Path:
    """
    Resolve the root that holds bundled code resources (config YAML).

    - Source run: workspace root.
    - Frozen run: PyInstaller bundle dir (`_internal`), where the spec places
      `fitting/*/config/*.yaml`. User data still lives under `runtime_project_root`.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and meipass:
        return Path(meipass).resolve()
    return Path(__file__).resolve().parents[3]


def raman_config_dir() -> Path:
    """Config folder shared by GUI, manual refit, and the desktop editor."""
    return runtime_resource_root() / "fitting" / "mos2_raman" / "config"


THRESHOLDS_FILENAME = "thresholds.yaml"


def thresholds_path() -> Path:
    """
    Resolve the user-editable thresholds file merged into every pipeline config.

    - Source run: workspace root `thresholds.yaml`.
    - Frozen run: `thresholds.yaml` next to the exe; if the user removed it,
      fall back to the bundled copy in `_internal`.
    """
    if getattr(sys, "frozen", False):
        external = Path(sys.executable).resolve().parent / THRESHOLDS_FILENAME
        if external.exists():
            return external
    return runtime_resource_root() / THRESHOLDS_FILENAME
