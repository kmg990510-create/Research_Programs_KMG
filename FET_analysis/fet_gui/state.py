"""Shared page state: data folders, the active batch, cached analysis, chrome and body filters.

Pages call ``active()`` and get the analysed run with the review applied. The
analysis itself is in ``fet_core`` and knows nothing about Streamlit.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from fet_core.config import load_config
from fet_core.pipeline import Run, results_frame, run_folder
from fet_core.review import ReviewState, load_review, save_review
from labkit.chrome import is_unified_mode, render_masthead, render_stage_header, resolve_page, sidebar_section_label
from labkit.sidebar import sidebar_section

FET_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_BATCH_KEY = "fet_active_batch"
FILTER_STORE_KEY = "fet_filter_store"
REVIEW_FILE = "review.json"
STATUS_ORDER = ("valid", "attention", "invalid")


def data_root() -> Path:
    """``FET_analysis/data``, or the folder named by ``FET_DATA_ROOT``."""
    return Path(os.environ.get("FET_DATA_ROOT", FET_ROOT / "data"))


def raw_root() -> Path:
    return data_root() / "raw"


def results_root() -> Path:
    return data_root() / "results"


def list_batches() -> list[str]:
    """Folders under ``data/raw`` that hold at least one file."""
    root = raw_root()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and any(f.is_file() for f in p.iterdir()))


def safe_batch_name(name: str) -> str:
    return re.sub(r"[^\w\-#.()]+", "_", name.strip()).strip("._")


def review_path(batch: str) -> Path:
    return results_root() / batch / REVIEW_FILE


def get_review(batch: str) -> ReviewState:
    return load_review(review_path(batch))


def put_review(batch: str, review: ReviewState) -> None:
    save_review(review_path(batch), review)


def _signature(folder: Path) -> tuple:
    return tuple(sorted((f.name, f.stat().st_size, f.stat().st_mtime_ns) for f in folder.iterdir() if f.is_file()))


@st.cache_resource(show_spinner="Analysing the batch…", max_entries=8)
def _cached_run(folder: str, signature: tuple, analysis_inputs: str) -> Run:
    """Re-run only when the files or the analysis inputs of the review change."""
    _ = signature
    review = ReviewState.from_dict(json.loads(analysis_inputs))
    return run_folder(folder, load_config(), review)


def render_fet_chrome(active_stage: str, page_title: str) -> None:
    """Render page config (standalone), top masthead, program title and workflow bar."""
    if not is_unified_mode():
        st.set_page_config(page_title=page_title, layout="wide")
        render_masthead("FET Analysis · Transfer Review")
    stages = (
        ("Run", resolve_page("fet", "run", "Run.py")),
        ("Devices", resolve_page("fet", "devices", "pages/1_Devices.py")),
        ("Compare", resolve_page("fet", "compare", "pages/2_Compare.py")),
        ("Finalize", resolve_page("fet", "finalize", "pages/3_Finalize.py")),
    )
    render_stage_header("FET Analysis", stages, active_stage, key_prefix="fet_stage")


def choose_batch() -> str | None:
    """Sidebar batch picker (expanded). Returns None when no batch exists yet."""
    batches = list_batches()
    with sidebar_section(sidebar_section_label(1, "Batch"), expanded=True):
        if not batches:
            st.caption("No batch yet. Add measurement files on the Run page.")
            return None
        current = st.session_state.get(ACTIVE_BATCH_KEY)
        index = batches.index(current) if current in batches else len(batches) - 1
        batch = st.selectbox("Batch", batches, index=index, help="A folder under data/raw. One folder is one batch.")
        st.session_state[ACTIVE_BATCH_KEY] = batch
        st.caption(f"Folder: {raw_root() / batch}")
    return batch


def load_run(batch: str, review: ReviewState) -> Run:
    folder = raw_root() / batch
    return _cached_run(str(folder), _signature(folder), json.dumps(review.analysis_inputs(), sort_keys=True))


def active() -> tuple[str, Run, ReviewState, pd.DataFrame]:
    """Batch name, analysed run, review and the reviewed result table; stops the page when there is nothing to show."""
    batch = choose_batch()
    if batch is None:
        st.info("No batch to show. Open the **Run** page and add measurement files.")
        st.stop()
    review = get_review(batch)
    run = load_run(batch, review)
    frame = results_frame(run, review)
    if frame.empty:
        st.warning("This batch has no transfer measurements. Check the file list on the **Run** page.")
        st.stop()
    return batch, run, review, frame


def sync_renamed_filter_groups(name_map: dict[str, str]) -> None:
    """Keep selected groups active in the persistent filter store when groups are renamed."""
    store = st.session_state.get(FILTER_STORE_KEY)
    if isinstance(store, dict) and "groups" in store:
        updated = [name_map.get(g, g) for g in store["groups"]]
        store["groups"] = list(dict.fromkeys(updated))
        if "fet_filter_groups" in st.session_state:
            st.session_state["fet_filter_groups"] = list(store["groups"])


def filters(frame: pd.DataFrame, groups: list[str]) -> pd.DataFrame:
    """Body filter row shared across Devices and Compare."""
    batch_id = st.session_state.get(ACTIVE_BATCH_KEY, "__default__")
    sweeps = list(dict.fromkeys(frame["sweep"]))
    statuses = [s for s in STATUS_ORDER if s in set(frame["status"])]

    store = st.session_state.setdefault(FILTER_STORE_KEY, {})
    batch_changed = store.get("batch") != batch_id
    if batch_changed:
        store.update(
            batch=batch_id,
            groups=list(groups),
            sweeps=list(sweeps[:1]),
            statuses=list(statuses),
            show_rejected=True,
        )
    else:
        store["groups"] = [g for g in store.get("groups", groups) if g in groups]
        store["sweeps"] = [s for s in store.get("sweeps", sweeps[:1]) if s in sweeps]
        store["statuses"] = [s for s in store.get("statuses", statuses) if s in statuses]
        store.setdefault("show_rejected", True)

    if batch_changed or st.session_state.get("fet_filter_last_batch") != batch_id:
        st.session_state["fet_filter_groups"] = list(store["groups"])
        st.session_state["fet_filter_sweeps"] = list(store["sweeps"])
        st.session_state["fet_filter_status"] = list(store["statuses"])
        st.session_state["fet_filter_rejected"] = bool(store["show_rejected"])
    else:
        if "fet_filter_groups" not in st.session_state:
            st.session_state["fet_filter_groups"] = list(store["groups"])
        else:
            st.session_state["fet_filter_groups"] = [g for g in st.session_state["fet_filter_groups"] if g in groups]
        if "fet_filter_sweeps" not in st.session_state:
            st.session_state["fet_filter_sweeps"] = list(store["sweeps"])
        else:
            st.session_state["fet_filter_sweeps"] = [s for s in st.session_state["fet_filter_sweeps"] if s in sweeps]
        if "fet_filter_status" not in st.session_state:
            st.session_state["fet_filter_status"] = list(store["statuses"])
        else:
            st.session_state["fet_filter_status"] = [s for s in st.session_state["fet_filter_status"] if s in statuses]
        if "fet_filter_rejected" not in st.session_state:
            st.session_state["fet_filter_rejected"] = bool(store["show_rejected"])

    c_grp, c_swp, c_sts, c_rej = st.columns([1.9, 1.25, 1.35, 1.5], vertical_alignment="bottom")
    chosen_groups = c_grp.multiselect("Groups", groups, key="fet_filter_groups", placeholder="No groups selected")
    chosen_sweeps = c_swp.multiselect(
        "Sweep direction",
        sweeps,
        key="fet_filter_sweeps",
        placeholder="No sweeps",
        help="Each sweep direction of a measurement is one row with its own values and decision.",
    )
    chosen_statuses = c_sts.multiselect("Status", statuses, key="fet_filter_status", placeholder="No statuses")
    show_rejected = c_rej.checkbox("Show rejected sweeps", key="fet_filter_rejected")

    store.update(
        batch=batch_id,
        groups=list(chosen_groups),
        sweeps=list(chosen_sweeps),
        statuses=list(chosen_statuses),
        show_rejected=bool(show_rejected),
    )
    st.session_state["fet_filter_last_batch"] = batch_id

    mask = frame["sweep"].isin(chosen_sweeps) & frame["status"].isin(chosen_statuses) & frame["group_display"].isin(chosen_groups)
    if not show_rejected:
        mask &= frame["decision"] != "rejected"
    return frame[mask]


def stop_if_empty(frame: pd.DataFrame) -> None:
    if frame.empty:
        st.info("No sweeps match the current filters.")
        st.stop()
