"""Helpers to discover and load pipeline report artifacts."""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import importlib
import sys

import pandas as pd
import streamlit as st

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.append(str(_BOOTSTRAP_ROOT))

from fitting.mos2_core.core import runtime_paths as _runtime_paths

if not hasattr(_runtime_paths, "is_cloud_runtime"):
    importlib.reload(_runtime_paths)

from fitting.mos2_core.core.runtime_paths import is_cloud_runtime
from fitting.mos2_core.core.runtime_paths import raman_config_dir as _bundled_raman_config_dir
from fitting.mos2_core.core.runtime_paths import runtime_project_root
from fitting.mos2_core.review import manual_overrides as _manual_overrides_mod

importlib.reload(_manual_overrides_mod)

from fitting.mos2_core.review.manual_overrides import (
    apply_manual_overrides_to_payload,
    override_mtime_ns_for_report,
    override_path_for_report,
)

SUPPORTED_MODALITIES = ("raman", "pl")


def project_root() -> Path:
    return runtime_project_root(__file__, 2)


def results_dir() -> Path:
    return project_root() / "data" / "results"


def raman_config_dir() -> Path:
    return _bundled_raman_config_dir()


@st.cache_data(show_spinner=False)
def load_graph_config() -> dict[str, Any]:
    # No silent fallback: a broken config.yaml must show its error instead of the GUI
    # quietly using section-file values without the user's settings.
    from fitting.mos2_core.io import load_pipeline_config

    config = load_pipeline_config(raman_config_dir())
    return dict(config["raman_graph"])


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
def load_report_payload(
    path_str: str,
    cache_bust_mtime_ns: int | None = None,
    manual_overrides_mtime_ns: int | None = None,
) -> dict:
    _ = cache_bust_mtime_ns
    _ = manual_overrides_mtime_ns
    path = Path(path_str)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return apply_manual_overrides_to_payload(payload, path)


@st.cache_data(show_spinner=False)
def load_spectra_dataframe(
    path_str: str,
    cache_bust_mtime_ns: int | None = None,
    manual_overrides_mtime_ns: int | None = None,
) -> pd.DataFrame:
    payload = load_report_payload(path_str, cache_bust_mtime_ns, manual_overrides_mtime_ns)
    spectra = payload.get("spectra", [])
    if isinstance(spectra, list):
        return pd.DataFrame(spectra)
    return pd.DataFrame()


def _infer_upload_modality(filename: str, content_bytes: bytes, fallback: str) -> str:
    lower_name = filename.lower()
    if lower_name.startswith("pl_") or "_pl_" in lower_name:
        return "pl"
    if lower_name.startswith("raman_") or "_raman_" in lower_name:
        return "raman"
    if lower_name.endswith(".json"):
        try:
            data = json.loads(content_bytes.decode("utf-8", errors="replace"))
            if isinstance(data, dict):
                mod = str(data.get("modality", "")).strip().lower()
                if mod in SUPPORTED_MODALITIES:
                    return mod
                spectra = data.get("spectra")
                if isinstance(spectra, list) and spectra and isinstance(spectra[0], dict):
                    row_mod = str(spectra[0].get("modality", "")).strip().lower()
                    if row_mod in SUPPORTED_MODALITIES:
                        return row_mod
                    if "pl_position" in spectra[0] or "a0_position" in spectra[0]:
                        return "pl"
        except Exception:
            pass
    return fallback if fallback in SUPPORTED_MODALITIES else "raman"


_JSON_ONLY_ROW_KEYS = frozenset(
    {
        "all_candidates",
        "fit_params",
        "fit_metrics",
        "fitted_y",
        "raw_x",
        "raw_y",
    }
)


def build_projected_report_json_bytes(payload: dict[str, Any]) -> bytes:
    """Serialize projected report payload (including embedded raw_x/raw_y and manual overrides) to JSON bytes."""
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def build_projected_csv_bytes(payload: dict[str, Any], fallback_csv_path: Path | None = None) -> bytes:
    """Build parameters CSV bytes from projected spectra rows so manual overrides/decisions are included."""
    spectra = payload.get("spectra", [])
    if not isinstance(spectra, list) or not spectra:
        if fallback_csv_path is not None and fallback_csv_path.exists():
            return fallback_csv_path.read_bytes()
        return b""

    base_fields: list[str] = []
    if fallback_csv_path is not None and fallback_csv_path.exists():
        try:
            with fallback_csv_path.open("r", encoding="utf-8", errors="replace", newline="") as fp:
                reader = csv.reader(fp)
                header = next(reader, None)
                if header:
                    base_fields = [str(col) for col in header if str(col) not in _JSON_ONLY_ROW_KEYS]
        except Exception:
            base_fields = []

    known_set = set(base_fields)
    extra_fields = sorted(
        {
            str(key)
            for row in spectra
            if isinstance(row, dict)
            for key in row.keys()
            if str(key) not in known_set and str(key) not in _JSON_ONLY_ROW_KEYS
        }
    )
    fieldnames = base_fields + extra_fields
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in spectra:
        if isinstance(row, dict):
            writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def save_uploaded_report_files(
    uploaded_files: list[Any],
    default_modality: str = "raman",
    base_results_dir: Path | None = None,
) -> list[Path]:
    target_root = base_results_dir if base_results_dir is not None else results_dir()
    saved_paths: list[Path] = []
    uploaded_names = {
        Path(str(getattr(item, "name", "") or "")).name
        for item in uploaded_files
        if getattr(item, "name", None)
    }
    for item in uploaded_files:
        raw_name = Path(str(getattr(item, "name", "") or "")).name
        if not raw_name:
            continue
        content = item.getvalue() if hasattr(item, "getvalue") else item.read()
        if not isinstance(content, (bytes, bytearray)):
            continue
        modality = _infer_upload_modality(raw_name, bytes(content), default_modality)
        if raw_name.endswith("_manual_overrides.json"):
            dest_dir = target_root / modality / "manual_refits"
        else:
            dest_dir = target_root / modality / "reports"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / raw_name
        dest_path.write_bytes(bytes(content))
        saved_paths.append(dest_path)
        if raw_name.endswith("_fit_report.json"):
            override_file = override_path_for_report(dest_path)
            if override_file.name not in uploaded_names and override_file.exists():
                try:
                    override_file.unlink()
                except OSError:
                    pass
    return saved_paths


def choose_report_sidebar(key_prefix: str = "global") -> tuple[Path | None, dict | None, pd.DataFrame]:
    files = list_report_json_files()
    cloud_mode = is_cloud_runtime()
    st.sidebar.subheader("1) Report Source")

    with st.sidebar.expander("Upload Report JSON / CSV", expanded=(cloud_mode or not bool(files))):
        uploaded = st.file_uploader(
            "Upload *_fit_report.json, *_fit_parameters.csv, or *_manual_overrides.json",
            type=["json", "csv"],
            accept_multiple_files=True,
            key=f"{key_prefix}_report_uploader",
        )
        if uploaded:
            upload_mod = st.selectbox(
                "Default modality for upload",
                options=list(SUPPORTED_MODALITIES),
                index=0,
                key=f"{key_prefix}_report_upload_modality",
            )
            if st.button(
                "Save Uploaded Report(s)",
                key=f"{key_prefix}_report_upload_save_btn",
                use_container_width=True,
            ):
                saved = save_uploaded_report_files(uploaded, default_modality=upload_mod)
                if saved:
                    load_report_payload.clear()
                    load_spectra_dataframe.clear()
                    st.success(f"Saved {len(saved)} file(s).")
                    st.rerun()

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
    overrides_mtime_ns = override_mtime_ns_for_report(selected_path)
    payload = load_report_payload(str(selected_path), selected_mtime_ns, overrides_mtime_ns)
    df = load_spectra_dataframe(str(selected_path), selected_mtime_ns, overrides_mtime_ns)
    st.sidebar.caption(f"Path: {selected_path}")

    with st.sidebar.expander("Export / Save Intermediate State", expanded=cloud_mode):
        st.caption("Download the current report (includes raw spectra & all manual edits) to resume later.")
        csv_candidate = paired_csv_path(selected_path)
        st.download_button(
            "Export Intermediate JSON",
            data=build_projected_report_json_bytes(payload),
            file_name=selected_path.name,
            mime="application/json",
            key=f"{key_prefix}_sidebar_export_json",
            use_container_width=True,
        )
        st.download_button(
            "Export Parameters CSV",
            data=build_projected_csv_bytes(payload, csv_candidate),
            file_name=csv_candidate.name,
            mime="text/csv",
            key=f"{key_prefix}_sidebar_export_csv",
            use_container_width=True,
        )

    st.sidebar.divider()
    return selected_path, payload, df


def sidebar_filters_header() -> None:
    st.sidebar.subheader("2) Filters")


def sidebar_advanced_header() -> None:
    st.sidebar.subheader("3) Advanced")


def _is_raman_mapping_csv_bytes(data: bytes) -> bool:
    head = data[:16384].decode("utf-8", errors="replace")
    return "FILETYPE=RAMAN SPECTRUM (MAPPING)" in head.upper() or "X,Y,Z,XINDEX,YINDEX,ZINDEX," in head


def stage_uploaded_raw_files(
    uploaded_files: list[Any],
    *,
    modality: str,
    folder_name: str,
    base_raw_dir: Path | None = None,
    split_raman_mapping: bool = True,
) -> dict[str, Any]:
    """Save uploaded spectrum files (.txt, .asc, .csv, .zip) into data/raw/{modality}/{folder_name}."""
    from fitting.mos2_raman.split_mapping_csv import split_mapping_csv

    mod = modality.strip().lower() if modality.strip().lower() in SUPPORTED_MODALITIES else "raman"
    safe_folder = re.sub(r"[^\w\-]+", "_", folder_name.strip()).strip("_") or "uploaded_sample"
    raw_root = base_raw_dir if base_raw_dir is not None else (project_root() / "data" / "raw" / mod)
    target_dir = (raw_root / safe_folder).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    written_files = 0
    split_summaries: list[str] = []
    allowed_suffixes = {".txt", ".asc", ".csv"}

    def _handle_single_file(dest_path: Path, file_bytes: bytes) -> None:
        nonlocal written_files
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(file_bytes)
        written_files += 1
        if (
            split_raman_mapping
            and mod == "raman"
            and dest_path.suffix.lower() == ".csv"
            and _is_raman_mapping_csv_bytes(file_bytes)
        ):
            out_dir = dest_path.parent if len(uploaded_files) == 1 else dest_path.with_suffix("")
            res = split_mapping_csv(dest_path, out_dir=out_dir, overwrite=True)
            written_files += res.written
            split_summaries.append(
                f"{dest_path.name} -> {res.written}/{res.expected} points ({res.out_dir.name})"
            )

    for item in uploaded_files:
        raw_name = Path(str(getattr(item, "name", "") or "")).name
        if not raw_name:
            continue
        content = item.getvalue() if hasattr(item, "getvalue") else item.read()
        if not isinstance(content, (bytes, bytearray)):
            continue
        data_bytes = bytes(content)
        suffix = Path(raw_name).suffix.lower()

        if suffix == ".zip":
            with zipfile.ZipFile(io.BytesIO(data_bytes)) as zf:
                for member in zf.infolist():
                    if member.is_dir():
                        continue
                    rel_parts = [
                        part
                        for part in Path(member.filename.replace("\\", "/")).parts
                        if part not in ("", ".", "..", "/", "\\") and not part.startswith("__MACOSX")
                    ]
                    if not rel_parts or rel_parts[-1].startswith("."):
                        continue
                    member_suffix = Path(rel_parts[-1]).suffix.lower()
                    if member_suffix not in allowed_suffixes:
                        continue
                    dest = target_dir.joinpath(*rel_parts)
                    _handle_single_file(dest, zf.read(member))
        elif suffix in allowed_suffixes:
            _handle_single_file(target_dir / raw_name, data_bytes)

    return {
        "target_dir": target_dir,
        "written_files": written_files,
        "split_summaries": split_summaries,
    }

