"""Helpers to discover and load pipeline report artifacts."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from fitting.mos2_core.core.runtime_paths import runtime_project_root

SUPPORTED_MODALITIES = ("raman", "pl")


def project_root() -> Path:
    return runtime_project_root(__file__, 2)


def results_dir() -> Path:
    return project_root() / "data" / "results"


def raman_config_dir() -> Path:
    return project_root() / "fitting" / "mos2_raman" / "config"


@st.cache_data(show_spinner=False)
def load_graph_config() -> dict[str, Any]:
    try:
        from fitting.mos2_core.io import load_pipeline_config

        config = load_pipeline_config(raman_config_dir())
        graph_cfg = config.get("raman_graph", {}) if isinstance(config, dict) else {}
        if isinstance(graph_cfg, dict):
            return graph_cfg
    except Exception:
        pass

    try:
        import yaml

        path = raman_config_dir() / "raman_graph.yaml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def list_report_json_files() -> list[Path]:
    root = results_dir()
    if not root.exists():
        return []

    fit_candidates: list[Path] = []
    for modality in SUPPORTED_MODALITIES:
        modality_reports = root / modality / "reports"
        if not modality_reports.exists():
            continue
        fit_candidates.extend(modality_reports.glob("*_fit_report.json"))
        fit_candidates.extend(modality_reports.glob("**/*_fit_report.json"))

    deduped_fit = {p.resolve(): p for p in fit_candidates}
    return sorted(deduped_fit.values(), key=lambda p: p.stat().st_mtime, reverse=True)


def paired_csv_path(json_path: Path) -> Path:
    if json_path.name.endswith("_fit_report.json"):
        return json_path.with_name(json_path.name.replace("_fit_report.json", "_fit_parameters.csv"))
    if json_path.name.endswith("_summary.json"):
        return json_path.with_name(json_path.name.replace("_summary.json", "_parameters.csv"))
    return json_path.with_suffix(".csv")


@st.cache_data(show_spinner=False)
def load_report_payload(path_str: str, cache_bust_mtime_ns: int | None = None) -> dict:
    _ = cache_bust_mtime_ns
    path = Path(path_str)
    return json.loads(path.read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def load_spectra_dataframe(path_str: str, cache_bust_mtime_ns: int | None = None) -> pd.DataFrame:
    payload = load_report_payload(path_str, cache_bust_mtime_ns)
    spectra = payload.get("spectra", [])
    if isinstance(spectra, list):
        return pd.DataFrame(spectra)
    return pd.DataFrame()


def choose_report_sidebar(key_prefix: str = "global") -> tuple[Path | None, dict | None, pd.DataFrame]:
    files = list_report_json_files()
    st.sidebar.subheader("1) Report Source")

    if not files:
        st.sidebar.warning(
            "No report JSON found in data/results/{raman,pl}/reports."
        )
        return None, None, pd.DataFrame()

    labels = [
        f"{path.name}  ({datetime.fromtimestamp(path.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')})"
        for path in files
    ]
    selected_label = st.sidebar.selectbox("Select report", labels, key=f"{key_prefix}_report")
    selected_path = files[labels.index(selected_label)]

    selected_mtime_ns = int(selected_path.stat().st_mtime_ns)
    payload = load_report_payload(str(selected_path), selected_mtime_ns)
    df = load_spectra_dataframe(str(selected_path), selected_mtime_ns)
    st.sidebar.caption(f"Path: {selected_path}")
    st.sidebar.divider()
    return selected_path, payload, df


def sidebar_filters_header() -> None:
    st.sidebar.subheader("2) Filters")


def sidebar_advanced_header() -> None:
    st.sidebar.subheader("3) Advanced")

