"""Page for running Raman/PL analysis from folder selection."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import streamlit as st

from fitting.mos2_core.core.runtime_paths import runtime_project_root  # noqa: E402

ROOT = runtime_project_root(__file__, 2)
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from gui.components import data_bin as _data_bin  # noqa: E402

STAGES = ("fit", "select", "review")
START_RE = re.compile(r"^\[(fit|select|review)\]\s+start:\s+(\d+)\s+spectra\s*$")
FIT_SELECT_RE = re.compile(
    r"^\[(fit|select)\]\s+(\d+)/(\d+)\s+\|\s+valid=(\d+)\s+attention=(\d+)\s+invalid=(\d+)\s+\|\s+elapsed=([0-9.]+)s\s*$"
)
REVIEW_RE = re.compile(
    r"^\[review\]\s+(\d+)/(\d+)\s+\|\s+flagged_valid=(\d+)/(\d+)\s+\|\s+queue=(\d+)\s+\|\s+elapsed=([0-9.]+)s\s*$"
)
REPORT_LINE_RE = re.compile(r"^Fit report \((JSON|CSV)\):\s*(.+)\s*$")
BATCH_HEADER_RE = re.compile(r"^\[Batch\s+(\d+)/(\d+)\]\s+run_id=(.+?)\s+\|\s+raw_dir=(.+)\s*$")

list_scope_items = _data_bin.list_scope_items
list_bin_entries = _data_bin.list_bin_entries
move_scope_item_to_bin = _data_bin.move_scope_item_to_bin
restore_bin_entry = _data_bin.restore_bin_entry
purge_bin_entry = _data_bin.purge_bin_entry
RESULT_BIN_SCOPE = "results"


def _frozen_tool_executable(stem: str) -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    suffix = ".exe" if os.name == "nt" else ""
    candidate = Path(sys.executable).resolve().with_name(f"{stem}{suffix}")
    return candidate if candidate.exists() else None


@st.cache_data(show_spinner=False)
def _discover_txt_folders(base_dir: str) -> list[str]:
    root = Path(base_dir)
    if not root.exists():
        return []

    found: list[str] = []
    try:
        if any(root.glob("*.txt")):
            found.append(str(root))
    except OSError:
        pass

    for path in root.rglob("*"):
        if not path.is_dir():
            continue
        try:
            if any(path.glob("*.txt")):
                found.append(str(path))
        except OSError:
            # Ignore transient filesystem access issues and continue scanning.
            continue
    return sorted(found, key=lambda p: p.lower())


@st.cache_data(show_spinner=False)
def _discover_batch_parent_folders(base_dir: str) -> list[str]:
    root = Path(base_dir)
    if not root.exists():
        return []

    parents: set[str] = set()
    for txt_folder in _discover_txt_folders(base_dir):
        parent = Path(txt_folder).parent
        if parent.exists() and parent.is_dir():
            parents.add(str(parent))

    try:
        has_direct_txt_subdir = any(
            child.is_dir() and any(child.glob("*.txt"))
            for child in root.iterdir()
        )
        if has_direct_txt_subdir:
            parents.add(str(root))
    except OSError:
        pass

    return sorted(parents, key=lambda p: p.lower())


def _suggest_run_id(folder: Path) -> str:
    name = folder.name.strip() or "run"
    sanitized = re.sub(r"[^\w\-]+", "_", name).strip("_")
    return sanitized or "run"


def _resolve_selected_folder(base_raw_dir: Path, mode: str, selected: str, custom: str) -> Path:
    custom_clean = custom.strip()
    if mode == "custom" and custom_clean:
        custom_path = Path(custom_clean)
        return custom_path if custom_path.is_absolute() else (ROOT / custom_path).resolve()

    if selected:
        selected_path = Path(selected)
        return selected_path if selected_path.is_absolute() else (ROOT / selected_path).resolve()

    return base_raw_dir.resolve()


def _normalize_path_key(path_value: str | Path) -> str:
    try:
        return str(Path(path_value).resolve()).replace("/", "\\").lower()
    except (OSError, RuntimeError, ValueError):
        return str(path_value).replace("/", "\\").lower()


def _discover_immediate_targets(parent_dir: Path, pattern: str) -> list[Path]:
    if not parent_dir.exists() or not parent_dir.is_dir():
        return []
    targets: list[Path] = []
    try:
        for subdir in sorted((p for p in parent_dir.iterdir() if p.is_dir()), key=lambda p: p.name.lower()):
            if any(subdir.glob(pattern)):
                targets.append(subdir)
    except OSError:
        return []
    return targets


def _build_fit_progress_plan(selected_folder: Path, run_mode: str, pattern: str, run_id: str) -> dict[str, Any]:
    targets: list[dict[str, Any]] = []
    if not selected_folder.exists() or not selected_folder.is_dir():
        return {"targets": targets, "total_files": 0}

    def _append_target(folder: Path, effective_run_id: str) -> None:
        try:
            files = sorted(folder.glob(pattern))
        except OSError:
            files = []
        if not files:
            return
        targets.append(
            {
                "key": _normalize_path_key(folder),
                "run_id": effective_run_id,
                "raw_dir": str(folder.resolve()),
                "files": [path.name for path in files],
                "file_count": len(files),
            }
        )

    if run_mode == "batch_subdirs":
        for subdir in _discover_immediate_targets(selected_folder, pattern):
            _append_target(subdir, subdir.name)
    else:
        try:
            direct_files = sorted(selected_folder.glob(pattern))
        except OSError:
            direct_files = []
        if direct_files:
            _append_target(selected_folder, run_id)
        else:
            for subdir in _discover_immediate_targets(selected_folder, pattern):
                _append_target(subdir, subdir.name)

    return {
        "targets": targets,
        "total_files": sum(int(target["file_count"]) for target in targets),
    }


def _render_fit_card(slot: Any, title: str, fit_state: dict[str, Any], total_override: int | None = None) -> None:
    done = int(fit_state.get("done", 0))
    total = int(total_override if total_override is not None else fit_state.get("total", 0))
    valid = int(fit_state.get("valid", 0))
    attention = int(fit_state.get("attention", 0))
    invalid = int(fit_state.get("invalid", 0))
    elapsed = float(fit_state.get("elapsed", 0.0))

    progress = 0.0 if total <= 0 else min(max(done / total, 0.0), 1.0)
    eta_text = "eta: waiting"
    if elapsed > 0 and total > 0 and 0 < done < total:
        eta = (elapsed / done) * (total - done)
        eta_text = f"eta: ~{eta:.1f}s"
    elif total > 0 and done >= total:
        eta_text = "eta: done"

    with slot.container():
        st.markdown(f"**{title}**")
        st.progress(progress)
        if total > 0:
            st.caption(f"{done}/{total} ({progress * 100:.1f}%)")
        else:
            st.caption("waiting for first fit progress event")
        st.caption(f"valid={valid} | attention={attention} | invalid={invalid}")
        st.caption(f"elapsed: {elapsed:.1f}s")
        st.caption(eta_text)


def _stream_command_output(
    cmd: list[str],
    *,
    run_mode: str,
    selected_folder: Path,
    pattern: str,
    run_id: str,
    keep_last_lines: int = 1200,
) -> tuple[int, int, dict[str, str]]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    process = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )

    fit_plan = _build_fit_progress_plan(
        selected_folder=selected_folder,
        run_mode=run_mode,
        pattern=pattern,
        run_id=run_id.strip() or "run",
    )
    planned_targets: list[dict[str, Any]] = fit_plan["targets"]
    planned_total_files = int(fit_plan["total_files"])
    target_order = {target["key"]: idx + 1 for idx, target in enumerate(planned_targets)}
    targets_by_key: dict[str, dict[str, Any]] = {target["key"]: target for target in planned_targets}

    fit_by_target: dict[str, dict[str, Any]] = {}
    for target in planned_targets:
        fit_by_target[target["key"]] = {
            "run_id": target["run_id"],
            "raw_dir": target["raw_dir"],
            "files": list(target["files"]),
            "total": int(target["file_count"]),
            "done": 0,
            "valid": 0,
            "attention": 0,
            "invalid": 0,
            "elapsed": 0.0,
        }

    overview_slot = st.empty()
    current_fit_slot = st.empty() if run_mode == "batch_subdirs" else None
    current_batch_text_slot = st.empty() if run_mode == "batch_subdirs" else None

    with st.expander("Raw Logs (advanced)", expanded=False):
        logs = st.empty()

    lines: list[str] = []
    omitted = 0
    artifacts: dict[str, str] = {}
    current_target_key = planned_targets[0]["key"] if planned_targets else ""
    current_batch_index = 1 if (run_mode == "batch_subdirs" and planned_targets) else 0
    current_batch_total = len(planned_targets) if run_mode == "batch_subdirs" else 0

    def _ensure_target_state(path_hint: str) -> str:
        key = _normalize_path_key(path_hint)
        if key not in fit_by_target:
            guessed_run_id = Path(path_hint).name or "run"
            fit_by_target[key] = {
                "run_id": guessed_run_id,
                "raw_dir": path_hint,
                "files": [],
                "total": 0,
                "done": 0,
                "valid": 0,
                "attention": 0,
                "invalid": 0,
                "elapsed": 0.0,
            }
        return key

    def _render_progress() -> None:
        total_done = sum(int(item.get("done", 0)) for item in fit_by_target.values())
        total_valid = sum(int(item.get("valid", 0)) for item in fit_by_target.values())
        total_attention = sum(int(item.get("attention", 0)) for item in fit_by_target.values())
        total_invalid = sum(int(item.get("invalid", 0)) for item in fit_by_target.values())
        total_elapsed = sum(float(item.get("elapsed", 0.0)) for item in fit_by_target.values())

        total_files = planned_total_files
        if total_files <= 0:
            total_files = sum(max(int(item.get("total", 0)), 0) for item in fit_by_target.values())
        if total_files < total_done:
            total_files = total_done

        overall_state = {
            "done": total_done,
            "total": total_files,
            "valid": total_valid,
            "attention": total_attention,
            "invalid": total_invalid,
            "elapsed": total_elapsed,
        }

        if run_mode == "batch_subdirs":
            _render_fit_card(overview_slot, "Overall (fit only)", overall_state, total_override=total_files)
            current_state = fit_by_target.get(current_target_key)
            if current_state is None and fit_by_target:
                current_state = next(iter(fit_by_target.values()))

            if current_state is not None and current_fit_slot is not None:
                _render_fit_card(current_fit_slot, "Current Fit", current_state)
                if current_batch_text_slot is not None:
                    with current_batch_text_slot.container():
                        order_idx = target_order.get(current_target_key, current_batch_index)
                        if order_idx <= 0:
                            order_idx = current_batch_index or 1
                        total_batches = current_batch_total or max(len(fit_by_target), 1)
                        st.caption(
                            f"Current batch: {order_idx}/{total_batches} | run_id={current_state.get('run_id', 'run')}"
                        )
                        st.caption(f"Current folder: {current_state.get('raw_dir', '-')}")
                        files = current_state.get("files", [])
                        done = int(current_state.get("done", 0))
                        total = int(current_state.get("total", 0))
                        if isinstance(files, list) and files:
                            if done < total:
                                idx = min(max(done, 0), len(files) - 1)
                                st.caption(f"Current file (est.): {files[idx]}")
                            else:
                                idx = min(max(done - 1, 0), len(files) - 1)
                                st.caption(f"Last processed file: {files[idx]}")
        else:
            current_state = fit_by_target.get(current_target_key, overall_state)
            _render_fit_card(overview_slot, "Fit Progress", current_state)

    assert process.stdout is not None
    for raw_line in iter(process.stdout.readline, ""):
        if raw_line == "" and process.poll() is not None:
            break
        line = raw_line.rstrip("\r\n")
        lines.append(line)
        if len(lines) > keep_last_lines:
            overflow = len(lines) - keep_last_lines
            lines = lines[-keep_last_lines:]
            omitted += overflow

        batch_header = BATCH_HEADER_RE.match(line)
        if batch_header:
            current_batch_index = int(batch_header.group(1))
            current_batch_total = int(batch_header.group(2))
            run_id_text = batch_header.group(3).strip()
            raw_dir_text = batch_header.group(4).strip()
            current_target_key = _ensure_target_state(raw_dir_text)
            fit_by_target[current_target_key]["run_id"] = run_id_text or fit_by_target[current_target_key]["run_id"]
            fit_by_target[current_target_key]["raw_dir"] = raw_dir_text
            if current_target_key not in target_order:
                target_order[current_target_key] = current_batch_index

        start_match = START_RE.match(line)
        if start_match and start_match.group(1) == "fit":
            if not current_target_key:
                current_target_key = _ensure_target_state(str(selected_folder))
            fit_by_target[current_target_key]["total"] = int(start_match.group(2))
            if not fit_by_target[current_target_key].get("files"):
                candidate = targets_by_key.get(current_target_key)
                if isinstance(candidate, dict):
                    fit_by_target[current_target_key]["files"] = list(candidate.get("files", []))

        fit_match = FIT_SELECT_RE.match(line)
        if fit_match and fit_match.group(1) == "fit":
            if not current_target_key:
                current_target_key = _ensure_target_state(str(selected_folder))
            fit_state = fit_by_target[current_target_key]
            fit_state["done"] = int(fit_match.group(2))
            fit_state["total"] = int(fit_match.group(3))
            fit_state["valid"] = int(fit_match.group(4))
            fit_state["attention"] = int(fit_match.group(5))
            fit_state["invalid"] = int(fit_match.group(6))
            fit_state["elapsed"] = float(fit_match.group(7))

        report_match = REPORT_LINE_RE.match(line)
        if report_match:
            artifacts[report_match.group(1).lower()] = report_match.group(2).strip()

        _render_progress()

        display = lines
        if omitted:
            display = [f"[... {omitted} earlier lines omitted ...]", *lines]
        logs.code("\n".join(display), language="text")

    process.stdout.close()
    return_code = process.wait()

    _render_progress()
    return return_code, omitted, artifacts


st.title("Run Analysis")
st.caption("Select a raw folder and run Raman/PL analysis without typing CLI arguments.")

modality = st.selectbox("Modality", options=["raman", "pl"], index=0)
module_name = "fitting.mos2_raman.run_raw_pipeline" if modality == "raman" else "fitting.mos2_pl.run_raw_pipeline"
runner_stem = "mos2-run-raman" if modality == "raman" else "mos2-run-pl"
base_raw_dir = ROOT / "data" / "raw" / modality

with st.expander("Result Bin (optional): move results / restore / delete later", expanded=False):
    st.caption("Raw data is not touched here. Only data/results/* files are staged to Bin.")

    result_items = list_scope_items(
        ROOT,
        scope=RESULT_BIN_SCOPE,
        modality=modality,
        recursive=True,
        files_only=True,
    )
    result_item_labels = [path.as_posix() for path in result_items]
    st.markdown("**A) Move Result Files to Bin**")
    if result_item_labels:
        selected_result_items = st.multiselect(
            "Select result files to move into Bin",
            options=result_item_labels,
            key=f"run_analysis_result_bin_select::{modality}",
        )
        move_confirm = st.checkbox(
            "Confirm move of selected result files to Bin",
            key=f"run_analysis_result_bin_move_confirm::{modality}",
        )
        move_clicked = st.button(
            "Move Selected Results to Bin",
            key=f"run_analysis_result_bin_move_btn::{modality}",
            use_container_width=True,
            disabled=(not selected_result_items) or (not move_confirm),
        )
        if move_clicked:
            moved_count = 0
            with st.spinner("Moving selected result files to Bin..."):
                for rel_path in selected_result_items:
                    try:
                        move_scope_item_to_bin(
                            ROOT,
                            scope=RESULT_BIN_SCOPE,
                            modality=modality,
                            relative_path=rel_path,
                        )
                        moved_count += 1
                    except Exception as exc:  # pragma: no cover - UI feedback path
                        st.error(f"Failed to move '{rel_path}' to Bin: {exc}")
            if moved_count > 0:
                st.success(f"Moved {moved_count} result file(s) into Bin.")
                st.rerun()
    else:
        st.info("No result files found under current modality results root.")

    st.divider()
    st.markdown("**B) Bin Items**")
    entries = list_bin_entries(ROOT, scope=RESULT_BIN_SCOPE, modality=modality)
    if not entries:
        st.info(f"Bin is empty for modality: {modality}")
    else:
        entry_label_map = {
            entry.entry_id: (
                f"{entry.original_relpath} | {entry.item_type} | "
                f"moved_at={entry.moved_at or 'unknown'}"
            )
            for entry in entries
        }
        st.dataframe(
            [
                {
                    "entry_id": entry.entry_id,
                    "original_relpath": entry.original_relpath,
                    "type": entry.item_type,
                    "moved_at": entry.moved_at,
                }
                for entry in entries
            ],
            width="stretch",
            hide_index=True,
        )
        selected_entry_ids = st.multiselect(
            "Select Bin entries",
            options=[entry.entry_id for entry in entries],
            format_func=lambda entry_id: entry_label_map.get(entry_id, entry_id),
            key=f"run_analysis_bin_entry_select::{modality}",
        )
        action_cols = st.columns(2)
        restore_clicked = action_cols[0].button(
            "Restore Selected",
            key=f"run_analysis_bin_restore_btn::{modality}",
            use_container_width=True,
            disabled=not selected_entry_ids,
        )
        purge_confirm = action_cols[1].checkbox(
            "Confirm permanent delete",
            key=f"run_analysis_bin_purge_confirm::{modality}",
        )
        purge_clicked = action_cols[1].button(
            "Delete Selected Permanently",
            key=f"run_analysis_bin_purge_btn::{modality}",
            use_container_width=True,
            disabled=(not selected_entry_ids) or (not purge_confirm),
        )

        if restore_clicked:
            restored_count = 0
            with st.spinner("Restoring selected Bin items..."):
                for entry_id in selected_entry_ids:
                    try:
                        restore_bin_entry(
                            ROOT,
                            scope=RESULT_BIN_SCOPE,
                            modality=modality,
                            entry_id=entry_id,
                        )
                        restored_count += 1
                    except Exception as exc:  # pragma: no cover - UI feedback path
                        st.error(f"Failed to restore '{entry_id}': {exc}")
            if restored_count > 0:
                st.success(f"Restored {restored_count} item(s) from Bin.")
                st.rerun()

        if purge_clicked:
            purged_count = 0
            with st.spinner("Permanently deleting selected Bin items..."):
                for entry_id in selected_entry_ids:
                    try:
                        purge_bin_entry(
                            ROOT,
                            scope=RESULT_BIN_SCOPE,
                            modality=modality,
                            entry_id=entry_id,
                        )
                        purged_count += 1
                    except Exception as exc:  # pragma: no cover - UI feedback path
                        st.error(f"Failed to delete '{entry_id}': {exc}")
            if purged_count > 0:
                st.success(f"Permanently deleted {purged_count} item(s) from Bin.")
                st.rerun()

st.subheader("Step 1. Choose Run Mode")
run_mode = st.radio(
    "Run type",
    options=["single", "batch_subdirs"],
    format_func=lambda value: "Single folder" if value == "single" else "Batch (immediate subfolders)",
    horizontal=True,
    help="Batch mode runs one pipeline per immediate subfolder that contains TXT files.",
)

if run_mode == "single":
    known_folders = _discover_txt_folders(str(base_raw_dir))
    if not known_folders:
        st.warning(f"No TXT-containing folders found under: {base_raw_dir}")
else:
    known_folders = _discover_batch_parent_folders(str(base_raw_dir))
    if not known_folders:
        st.warning(f"No batch parent folders found under: {base_raw_dir}")

st.subheader("Step 2. Choose Source Folder")
source_mode = st.radio(
    "Folder source",
    options=["known", "custom"],
    horizontal=True,
    help="Known: choose from discovered folders. Custom: enter any absolute/relative path.",
)

selected_known = ""
if source_mode == "known":
    options = known_folders if known_folders else [str(base_raw_dir)]
    selected_known = st.selectbox("Raw folder", options=options)

custom_folder = ""
if source_mode == "custom":
    custom_folder = st.text_input(
        "Custom raw folder path",
        value=str(base_raw_dir),
        help="Relative paths are resolved from workspace root.",
    )

selected_folder = _resolve_selected_folder(base_raw_dir, source_mode, selected_known, custom_folder)
st.code(str(selected_folder), language="text")

txt_count = 0
if selected_folder.exists() and selected_folder.is_dir():
    if run_mode == "single":
        txt_count = sum(1 for _ in selected_folder.glob("*.txt"))
        st.caption(f"TXT files in selected folder: {txt_count}")
    else:
        batch_targets = []
        try:
            for subdir in selected_folder.iterdir():
                if subdir.is_dir() and any(subdir.glob("*.txt")):
                    batch_targets.append(subdir)
        except OSError:
            batch_targets = []
        st.caption(f"Batch targets (immediate subfolders with TXT): {len(batch_targets)}")
else:
    st.caption("Selected folder is not available.")

source_key = str(selected_folder)
suggested = _suggest_run_id(selected_folder)
if st.session_state.get("run_analysis_run_id_source") != source_key:
    st.session_state["run_analysis_run_id_source"] = source_key
    st.session_state["run_analysis_run_id_value"] = suggested

st.subheader("Step 3. Execution Options")
run_id = st.text_input("Run ID", key="run_analysis_run_id_value", disabled=(run_mode == "batch_subdirs"))
pattern = st.text_input("Pattern", value="*.txt")
progress_every = st.number_input("Progress every N files", min_value=1, max_value=1000, value=1, step=1)
if run_mode == "batch_subdirs":
    st.caption("Batch mode uses each immediate subfolder name as run-id (`Run ID` field disabled).")

peak_n_mode = "auto"
distance_outlier_mode = "config"
delta_outlier_mode = "config"
si_calibration_mode = "config"

if modality == "raman":
    st.markdown("**Raman Advanced Options**")
    peak_mode_options = {
        "auto": "Auto (all configured models)",
        "peak_2_model": "2 peaks (peak_2_model)",
        "peak_3_model": "3 peaks (peak_3_model)",
        "peak_4_model": "4 peaks (peak_4_model)",
        "peak_5_model": "5 peaks (peak_5_model)",
    }
    peak_n_mode = st.selectbox(
        "peak_n_mode",
        options=list(peak_mode_options.keys()),
        format_func=lambda key: peak_mode_options[key],
        index=0,
        help="Choose fixed peak-model mode or keep automatic ensemble.",
    )

    toggle_options = {
        "config": "Use config default",
        "enabled": "Force enabled",
        "disabled": "Force disabled",
    }
    outlier_cols = st.columns(3)
    distance_outlier_mode = outlier_cols[0].selectbox(
        "distance_outlier",
        options=list(toggle_options.keys()),
        format_func=lambda key: toggle_options[key],
        index=0,
        help="Controls e2g/a1g distance outlier rule (mahalanobis_outlier).",
    )
    delta_outlier_mode = outlier_cols[1].selectbox(
        "delta_outlier",
        options=list(toggle_options.keys()),
        format_func=lambda key: toggle_options[key],
        index=0,
        help="Controls delta outlier rule vs dataset.",
    )
    si_calibration_mode = outlier_cols[2].selectbox(
        "si_calibration",
        options=list(toggle_options.keys()),
        format_func=lambda key: toggle_options[key],
        index=0,
        help="Controls Si calibration offset (x-axis shift) before fitting.",
    )
else:
    st.caption("Raman advanced options (`peak_n_mode`, outlier overrides, `si_calibration`) are available in Raman modality.")

pipeline_exe = _frozen_tool_executable(runner_stem)
if pipeline_exe is not None:
    cmd = [
        str(pipeline_exe),
        "--raw-dir",
        str(selected_folder),
        "--pattern",
        str(pattern),
        "--run-id",
        str(run_id),
        "--progress-every",
        str(int(progress_every)),
        "--peak-n-mode",
        str(peak_n_mode),
        "--distance-outlier",
        str(distance_outlier_mode),
        "--delta-outlier",
        str(delta_outlier_mode),
        "--si-calibration",
        str(si_calibration_mode),
    ]
else:
    cmd = [
        sys.executable,
        "-u",
        "-m",
        module_name,
        "--raw-dir",
        str(selected_folder),
        "--pattern",
        str(pattern),
        "--run-id",
        str(run_id),
        "--progress-every",
        str(int(progress_every)),
        "--peak-n-mode",
        str(peak_n_mode),
        "--distance-outlier",
        str(distance_outlier_mode),
        "--delta-outlier",
        str(delta_outlier_mode),
        "--si-calibration",
        str(si_calibration_mode),
    ]
if run_mode == "batch_subdirs":
    cmd.append("--batch-subdirs")

st.subheader("Command Preview")
st.code(" ".join(cmd), language="powershell")

run_clicked = st.button("Run Analysis", type="primary", use_container_width=True)
if run_clicked:
    if not selected_folder.exists():
        st.error(f"Selected folder does not exist: {selected_folder}")
        st.stop()
    if not selected_folder.is_dir():
        st.error(f"Selected path is not a directory: {selected_folder}")
        st.stop()

    st.subheader("Live Run Status")
    st.caption("Stage progress is visualized as cards. Raw log lines are available in the advanced expander.")
    try:
        with st.spinner("Running pipeline..."):
            returncode, omitted, artifacts = _stream_command_output(
                cmd,
                run_mode=run_mode,
                selected_folder=selected_folder,
                pattern=pattern,
                run_id=run_id,
            )
    except OSError as exc:
        st.error(f"Failed to start pipeline process: {exc}")
        st.stop()

    if returncode == 0:
        st.success("Pipeline completed successfully.")
    else:
        st.error(f"Pipeline failed with exit code {returncode}.")

    if omitted:
        st.caption(f"Large output detected. {omitted} earlier lines were hidden to keep the page responsive.")
    if artifacts:
        st.subheader("Generated Artifacts")
        if "json" in artifacts:
            st.code(artifacts["json"], language="text")
        if "csv" in artifacts:
            st.code(artifacts["csv"], language="text")
