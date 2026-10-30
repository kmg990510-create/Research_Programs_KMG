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


USER_CONFIG_FILENAME = "config.yaml"


def user_config_path() -> Path:
    """
    Resolve the user-editable config.yaml merged over every pipeline config section.

    - Source run: workspace root `config.yaml`.
    - Frozen run: `config.yaml` next to the exe; if the user removed it,
      fall back to the bundled copy in `_internal`.
    """
    if getattr(sys, "frozen", False):
        external = Path(sys.executable).resolve().parent / USER_CONFIG_FILENAME
        if external.exists():
            return external
    return runtime_resource_root() / USER_CONFIG_FILENAME
