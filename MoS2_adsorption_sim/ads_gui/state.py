"""Shared page state: data folders, active batch selection, cached batch loading, sidebar 1) and 2).

Pages call ``active()`` to obtain the loaded ``BatchRun``, ``ReviewState``, and
review-applied pose DataFrame. Heavy uMLIP calculations happen in ``ads_core``;
GUI pages only read completed batches or trigger ``run_batch`` from ``Run.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import shutil
from pathlib import Path

import pandas as pd
import streamlit as st

from ads_core.model import STATUS_ATTENTION, STATUS_INVALID, STATUS_VALID
from ads_core.pipeline import BatchRun, poses_frame
from ads_core.report.export import BATCH_STATE_FILE, load_batch_run
from ads_core.review import ReviewState, load_review, save_review
from labkit.sidebar import sidebar_section

SIM_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_BATCH_KEY = "ads_active_batch"
REVIEW_FILE = "review.json"
STATUS_ORDER = (STATUS_VALID, STATUS_ATTENTION, STATUS_INVALID)


def data_root() -> Path:
    """``MoS2_adsorption_sim/data``, or the folder named by ``ADS_DATA_ROOT``."""
    return Path(os.environ.get("ADS_DATA_ROOT", SIM_ROOT / "data"))


def molecules_root() -> Path:
    return data_root() / "molecules"


def results_root() -> Path:
    return data_root() / "results"


def bin_root() -> Path:
    return data_root() / "bin"


def _scope_root(scope: str) -> Path:
    if scope == "results":
        return results_root()
    if scope == "molecules":
        return molecules_root()
    raise ValueError(f"Unsupported data scope {scope!r}")


def _trash_item(source: Path, scope: str) -> Path:
    """Move a batch folder or molecule file into ``data/bin/<scope>/`` (soft-delete)."""
    if not source.exists():
        raise FileNotFoundError(f"Item not found: {source}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_frag = safe_batch_name(source.name) or "item"
    dest_dir = bin_root() / scope / f"{stamp}_{safe_frag}"
    suffix = 1
    while dest_dir.exists():
        suffix += 1
        dest_dir = bin_root() / scope / f"{stamp}_{safe_frag}_{suffix}"
    payload_dir = dest_dir / "payload"
    payload_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(payload_dir / source.name))
    meta = {
        "original_name": source.name,
        "scope": scope,
        "deleted_at": datetime.now(timezone.utc).isoformat(),
    }
    (dest_dir / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return dest_dir


def trash_batch(batch: str) -> Path:
    """Soft-delete a simulation batch by moving it to ``data/bin/results``."""
    target = results_root() / batch
    dest = _trash_item(target, "results")
    if st.session_state.get(ACTIVE_BATCH_KEY) == batch:
        st.session_state.pop(ACTIVE_BATCH_KEY, None)
    clear_run_cache()
    return dest


def trash_molecule_file(filename: str) -> Path:
    """Soft-delete an uploaded molecule file by moving it to ``data/bin/molecules``."""
    return _trash_item(molecules_root() / filename, "molecules")


def list_trashed_items(scope: str) -> list[dict[str, str]]:
    """List soft-deleted entries under ``data/bin/<scope>``."""
    root = bin_root() / scope
    if not root.is_dir():
        return []
    entries: list[dict[str, str]] = []
    for entry_dir in sorted(root.iterdir(), reverse=True):
        meta_file = entry_dir / "metadata.json"
        if not entry_dir.is_dir() or not meta_file.is_file():
            continue
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        entries.append(
            {
                "entry_id": entry_dir.name,
                "original_name": str(meta.get("original_name", entry_dir.name)),
                "deleted_at": str(meta.get("deleted_at", "")),
                "scope": scope,
            }
        )
    return entries


def restore_trashed_item(scope: str, entry_id: str) -> str:
    """Restore a soft-deleted batch or molecule file back to its original folder."""
    entry_dir = bin_root() / scope / entry_id
    meta = json.loads((entry_dir / "metadata.json").read_text(encoding="utf-8"))
    original_name = str(meta["original_name"])
    payload = entry_dir / "payload" / original_name
    if not payload.exists():
        raise FileNotFoundError(f"Trashed payload missing: {payload}")
    dest_root = _scope_root(scope)
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / original_name
    if dest.exists():
        raise FileExistsError(f"Target already exists: {dest}")
    shutil.move(str(payload), str(dest))
    shutil.rmtree(entry_dir)
    if scope == "results":
        clear_run_cache()
    return original_name


def delete_trashed_item_permanently(scope: str, entry_id: str) -> None:
    """Permanently remove a soft-deleted entry from ``data/bin/<scope>``."""
    entry_dir = bin_root() / scope / entry_id
    if entry_dir.is_dir():
        shutil.rmtree(entry_dir)


def list_batches() -> list[str]:
    """Subfolders under ``data/results`` containing a saved ``batch_state.json``."""
    root = results_root()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / BATCH_STATE_FILE).is_file())


def safe_batch_name(name: str) -> str:
    return re.sub(r"[^\w\-#.()]+", "_", name.strip()).strip("._")


def review_path(batch: str) -> Path:
    return results_root() / batch / REVIEW_FILE


def get_review(batch: str) -> ReviewState:
    return load_review(review_path(batch))


def put_review(batch: str, review: ReviewState) -> None:
    save_review(review_path(batch), review)


@st.cache_resource(show_spinner="Loading simulation batch...", max_entries=8)
def _cached_run(folder: str, state_mtime_ns: int) -> BatchRun:
    _ = state_mtime_ns
    return load_batch_run(folder)


def clear_run_cache() -> None:
    _cached_run.clear()


def load_run(batch: str) -> BatchRun:
    folder = results_root() / batch
    state_file = folder / BATCH_STATE_FILE
    return _cached_run(str(folder), int(state_file.stat().st_mtime_ns))


def choose_batch() -> str | None:
    """Sidebar section 1: select an existing batch from ``data/results``."""
    batches = list_batches()
    with sidebar_section("1) Batch"):
        if not batches:
            st.caption("No simulation batches in data/results yet. Run a batch on the Run page.")
            return None
        current = st.session_state.get(ACTIVE_BATCH_KEY)
        index = batches.index(current) if current in batches else len(batches) - 1
        batch = st.selectbox(
            "Simulation batch",
            batches,
            index=index,
            help="Each subfolder under data/results with batch_state.json is one simulation batch.",
        )
        st.session_state[ACTIVE_BATCH_KEY] = batch
        st.caption(f"Folder: {results_root() / batch}")
    return batch


def active() -> tuple[str, BatchRun, ReviewState, pd.DataFrame]:
    """Return active ``(batch, run, review, frame)`` or stop cleanly when none exists."""
    batch = choose_batch()
    if batch is None:
        st.info("No batch to display. Create and run a simulation batch on the **Run** page.")
        st.stop()
    run = load_run(batch)
    review = get_review(batch)
    frame = poses_frame(run, review)
    if frame.empty and not run.md_results:
        st.warning("This batch contains no evaluated poses or MD runs. Check Run settings or warnings.")
        st.stop()
    return batch, run, review, frame


def _sync_filter_state(key: str, options: list[str], batch_changed: bool) -> None:
    if key not in st.session_state:
        st.session_state[key] = list(options)
        return
    kept = [val for val in st.session_state[key] if val in options]
    if batch_changed and not kept:
        kept = list(options)
    st.session_state[key] = kept


def filters(frame: pd.DataFrame, groups: list[str]) -> pd.DataFrame:
    """Sidebar section 2: shared filters for surfaces, molecules, statuses, groups, rejected poses."""
    surfaces = list(dict.fromkeys(frame["surface_id"].astype(str)))
    molecules = list(dict.fromkeys(frame["molecule_id"].astype(str)))
    statuses = [s for s in STATUS_ORDER if s in set(frame["status"].astype(str))]

    batch_sig = (tuple(surfaces), tuple(molecules), tuple(groups), tuple(statuses))
    batch_changed = st.session_state.get("ads_filter_sig") != batch_sig
    st.session_state["ads_filter_sig"] = batch_sig

    _sync_filter_state("ads_filter_surfaces", surfaces, batch_changed)
    _sync_filter_state("ads_filter_molecules", molecules, batch_changed)
    _sync_filter_state("ads_filter_status", statuses, batch_changed)
    _sync_filter_state("ads_filter_groups", groups, batch_changed)
    st.session_state.setdefault("ads_filter_rejected", True)

    with sidebar_section("2) Filters"):
        chosen_surfaces = st.multiselect("Surface", surfaces, key="ads_filter_surfaces")
        chosen_molecules = st.multiselect("Molecule", molecules, key="ads_filter_molecules")
        chosen_statuses = st.multiselect("Status", statuses, key="ads_filter_status")
        chosen_groups = st.multiselect("Groups", groups, key="ads_filter_groups")
        show_rejected = st.checkbox("Show rejected poses", key="ads_filter_rejected")

    mask = (
        frame["surface_id"].isin(chosen_surfaces)
        & frame["molecule_id"].isin(chosen_molecules)
        & frame["status"].isin(chosen_statuses)
        & frame["group_display"].isin(chosen_groups)
    )
    if not show_rejected:
        mask &= frame["decision"] != "rejected"
    return frame[mask]


def stop_if_empty(frame: pd.DataFrame) -> None:
    if frame.empty:
        st.info("No poses match the active filters in the sidebar.")
        st.stop()


def render_data_manager(batch: str | None, existing_mol_files: list[Path]) -> None:
    """Render the soft-delete / trash restore expander used on Run.py."""
    trashed_batches = list_trashed_items("results")
    trashed_molecules = list_trashed_items("molecules")
    trash_total = len(trashed_batches) + len(trashed_molecules)

    with st.expander(f"Manage data (delete / trash: {trash_total})", expanded=False):
        if batch is not None:
            st.markdown("**Active simulation batch**")
            if st.button(f"Move batch '{batch}' to trash", key="run_trash_active_batch"):
                trash_batch(batch)
                st.toast(f"Moved batch '{batch}' to trash.")
                st.rerun()
        if existing_mol_files:
            st.markdown("**Uploaded molecule files**")
            del_mols = st.multiselect(
                "Select molecule files to move to trash",
                [p.name for p in existing_mol_files],
                default=[],
                key="run_trash_mol_select",
            )
            if st.button("Move selected molecule(s) to trash", disabled=not del_mols, key="run_trash_mols_btn"):
                for fname in del_mols:
                    trash_molecule_file(fname)
                st.toast(f"Moved {len(del_mols)} molecule file(s) to trash.")
                st.rerun()

        st.divider()
        st.markdown("**Trash bin (restore or permanently delete)**")
        if not trashed_batches and not trashed_molecules:
            st.caption("Trash is empty.")
            return

        trash_items = [
            {"scope": "results", "label": f"[Batch] {e['original_name']} ({e['deleted_at'][:19]})", **e}
            for e in trashed_batches
        ] + [
            {"scope": "molecules", "label": f"[Molecule] {e['original_name']} ({e['deleted_at'][:19]})", **e}
            for e in trashed_molecules
        ]
        labels = [item["label"] for item in trash_items]
        selected_label = st.selectbox("Trashed item", labels, key="run_trash_selected")
        selected_item = trash_items[labels.index(selected_label)]

        t1, t2 = st.columns(2)
        if t1.button("Restore selected item", key="run_restore_trash_btn"):
            try:
                restored_name = restore_trashed_item(selected_item["scope"], selected_item["entry_id"])
                if selected_item["scope"] == "results":
                    st.session_state[ACTIVE_BATCH_KEY] = restored_name
                st.toast(f"Restored '{restored_name}'.")
                st.rerun()
            except Exception as exc:
                st.error(f"Restore failed: {exc}")

        confirm_perm = t2.checkbox("Confirm permanent deletion", value=False, key="run_confirm_perm_delete")
        if t2.button(
            "Delete permanently",
            disabled=not confirm_perm,
            type="secondary",
            key="run_perm_delete_btn",
        ):
            delete_trashed_item_permanently(selected_item["scope"], selected_item["entry_id"])
            st.toast(f"Permanently deleted '{selected_item['original_name']}'.")
            st.rerun()
