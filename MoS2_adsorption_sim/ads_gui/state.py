"""Shared page state: data folders, active batch selection, cached batch loading, chrome, body filters."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from ads_core.model import STATUS_ATTENTION, STATUS_INVALID, STATUS_VALID
from ads_core.pipeline import BatchRun, poses_frame
from ads_core.report.export import BATCH_STATE_FILE, load_batch_run
from ads_core.review import ReviewState, load_review, save_review
from labkit.chrome import (
    is_unified_mode,
    render_masthead,
    render_stage_header,
    render_subnav,
    resolve_page,
    sidebar_section_label,
)
from labkit.sidebar import sidebar_section

SIM_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_BATCH_KEY = "ads_active_batch"
FILTER_STORE_KEY = "ads_filter_store"
POSES_SUB_STORE_KEY = "ads_poses_sub_last"
GROUPS_NONCE_KEY = "ads_compare_groups_nonce"
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


def _poses_target() -> object:
    if st.session_state.get(POSES_SUB_STORE_KEY) == "Coverage & Dimer":
        return resolve_page("ads", "coverage", "pages/4_Coverage_Dimer.py")
    return resolve_page("ads", "poses", "pages/1_Poses.py")


def render_ads_chrome(active_stage: str, page_title: str, *, poses_sub: str | None = None) -> None:
    """Render standalone page config, fixed masthead, program title, and workflow/sub-view bars."""
    if not is_unified_mode():
        st.set_page_config(page_title=page_title, layout="wide")
        render_masthead("MoS₂ Adsorption Sim · uMLIP + DFT-D3")

    if poses_sub in {"Single-Molecule Poses", "Coverage & Dimer"}:
        st.session_state[POSES_SUB_STORE_KEY] = poses_sub

    stages = (
        ("Run", resolve_page("ads", "run", "Run.py")),
        ("Poses", _poses_target()),
        ("Compare", resolve_page("ads", "compare", "pages/2_Compare.py")),
        ("Finalize", resolve_page("ads", "finalize", "pages/3_Finalize.py")),
    )
    render_stage_header("MoS₂ Adsorption Sim", stages, active_stage, key_prefix="ads_stage")

    if poses_sub is not None:
        render_subnav(
            "Poses mode",
            (
                ("Single-Molecule Poses", resolve_page("ads", "poses", "pages/1_Poses.py")),
                ("Coverage & Dimer", resolve_page("ads", "coverage", "pages/4_Coverage_Dimer.py")),
            ),
            poses_sub,
            key_prefix="ads_poses_sub",
        )


def choose_batch() -> str | None:
    """Sidebar section: select an existing batch from ``data/results``."""
    batches = list_batches()
    with sidebar_section(sidebar_section_label(1, "Batch"), expanded=True):
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


def sync_renamed_filter_groups(name_map: dict[str, str]) -> None:
    """Keep selected groups active in the persistent filter store when groups are renamed."""
    store = st.session_state.get(FILTER_STORE_KEY)
    if isinstance(store, dict) and "groups" in store:
        updated = [name_map.get(g, g) for g in store["groups"]]
        store["groups"] = list(dict.fromkeys(updated))
        if "ads_filter_groups" in st.session_state:
            st.session_state["ads_filter_groups"] = list(store["groups"])


def filters(frame: pd.DataFrame, groups: list[str]) -> pd.DataFrame:
    """Body filter row shared across Poses and Compare."""
    batch_id = st.session_state.get(ACTIVE_BATCH_KEY, "__default__")
    surfaces = list(dict.fromkeys(frame["surface_id"].astype(str))) if not frame.empty else []
    molecules = list(dict.fromkeys(frame["molecule_id"].astype(str))) if not frame.empty else []
    statuses = [s for s in STATUS_ORDER if s in set(frame["status"].astype(str))] if not frame.empty else []

    store = st.session_state.setdefault(FILTER_STORE_KEY, {})
    sig = (batch_id, tuple(surfaces), tuple(molecules), tuple(groups), tuple(statuses))
    batch_changed = store.get("batch") != batch_id
    sig_changed = store.get("sig") != sig

    if batch_changed:
        store.update(
            batch=batch_id,
            sig=sig,
            surfaces=list(surfaces),
            molecules=list(molecules),
            statuses=list(statuses),
            groups=list(groups),
            show_rejected=True,
        )
    else:
        store["sig"] = sig
        for k, opts in (
            ("surfaces", surfaces),
            ("molecules", molecules),
            ("statuses", statuses),
            ("groups", groups),
        ):
            kept = [v for v in store.get(k, opts) if v in opts]
            if sig_changed and not kept:
                kept = list(opts)
            store[k] = kept
        store.setdefault("show_rejected", True)

    widget_map = (
        ("ads_filter_surfaces", "surfaces", surfaces),
        ("ads_filter_molecules", "molecules", molecules),
        ("ads_filter_status", "statuses", statuses),
        ("ads_filter_groups", "groups", groups),
    )
    first_visit = st.session_state.get("ads_filter_last_batch") != batch_id
    for w_key, s_key, opts in widget_map:
        if first_visit or w_key not in st.session_state:
            st.session_state[w_key] = list(store[s_key])
        else:
            st.session_state[w_key] = [v for v in st.session_state[w_key] if v in opts]
    if first_visit or "ads_filter_rejected" not in st.session_state:
        st.session_state["ads_filter_rejected"] = bool(store["show_rejected"])

    c_srf, c_mol, c_sts, c_grp, c_rej = st.columns([1.4, 1.4, 1.2, 1.8, 1.1], vertical_alignment="bottom")
    chosen_surfaces = c_srf.multiselect("Surface", surfaces, key="ads_filter_surfaces")
    chosen_molecules = c_mol.multiselect("Molecule", molecules, key="ads_filter_molecules")
    chosen_statuses = c_sts.multiselect("Status", statuses, key="ads_filter_status")
    chosen_groups = c_grp.multiselect("Groups", groups, key="ads_filter_groups")
    show_rejected = c_rej.checkbox("Show rejected poses", key="ads_filter_rejected")

    store.update(
        batch=batch_id,
        sig=sig,
        surfaces=list(chosen_surfaces),
        molecules=list(chosen_molecules),
        statuses=list(chosen_statuses),
        groups=list(chosen_groups),
        show_rejected=bool(show_rejected),
    )
    st.session_state["ads_filter_last_batch"] = batch_id

    if frame.empty:
        return frame
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
        st.info("No poses match the active filters.")
        st.stop()


def render_group_manager_popover(
    batch: str,
    frame: pd.DataFrame,
    review: ReviewState,
    groups: list[str],
    *,
    container: Any,
) -> None:
    """Render the immediate-save group rename and ordering editor inside a popover."""
    with container.popover("Manage groups", width="stretch"):
        st.markdown("**Group display names and order**")
        if frame.empty:
            st.info("No relaxation groups in this MD-only batch.")
            return
        st.caption("Used across every plot and exported CSV. Changes are saved immediately to review.json.")
        st.session_state.setdefault(GROUPS_NONCE_KEY, 0)
        originals = list(dict.fromkeys(frame["group_key"].astype(str)))
        old_display_by_key = {g: review.display_group(g) for g in originals}
        table = pd.DataFrame(
            {
                "group key": originals,
                "name": [old_display_by_key[g] for g in originals],
                "order": [groups.index(old_display_by_key[g]) + 1 for g in originals],
            }
        )
        edited = st.data_editor(
            table,
            hide_index=True,
            width="stretch",
            disabled=["group key"],
            column_config={"order": st.column_config.NumberColumn("order", min_value=1, step=1, required=True)},
            key=f"ads_compare_groups_{batch}_{st.session_state[GROUPS_NONCE_KEY]}",
        )
        names = {r["group key"]: (str(r["name"] or "").strip() or r["group key"]) for r in edited.to_dict("records")}
        moved = edited["order"] != table["order"]
        if moved.any() or names != dict(zip(table["group key"], table["name"])):
            ranked = edited.assign(display=[names[g] for g in edited["group key"]], kept=~moved).sort_values(
                ["order", "kept"], kind="stable"
            )
            name_map = {old_display_by_key[g]: names[g] for g in originals}
            review.group_names = {g: n for g, n in names.items() if n != g}
            review.group_order = list(dict.fromkeys(ranked["display"]))
            put_review(batch, review)
            sync_renamed_filter_groups(name_map)
            st.session_state[GROUPS_NONCE_KEY] += 1
            st.rerun()


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
