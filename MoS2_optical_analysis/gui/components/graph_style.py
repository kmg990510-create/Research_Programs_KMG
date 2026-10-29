"""Shared graph-style loader for Streamlit and desktop editor views."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from fitting.mos2_core.core.runtime_paths import raman_config_dir

_GRAPH_PATH = raman_config_dir() / "raman_graph.yaml"


@lru_cache(maxsize=1)
def load_raman_graph_config_file() -> dict[str, Any]:
    """Load raw Raman graph config YAML with graceful fallback."""
    if not _GRAPH_PATH.exists():
        return {}
    try:
        import yaml

        payload = yaml.safe_load(_GRAPH_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def all_spectra_viewer_cfg() -> dict[str, Any]:
    payload = load_raman_graph_config_file()
    return _dict_or_empty(payload.get("all_spectra_viewer"))


def overlay_style_cfg() -> dict[str, Any]:
    return _dict_or_empty(all_spectra_viewer_cfg().get("style"))


def fit_curve_cfg() -> dict[str, Any]:
    return _dict_or_empty(all_spectra_viewer_cfg().get("fit_curve"))


def x_window_cfg() -> dict[str, Any]:
    return _dict_or_empty(all_spectra_viewer_cfg().get("x_window"))
