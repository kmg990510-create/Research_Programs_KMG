"""Shared page state: data folders, the active batch, its cached analysis, sidebar sections.

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
from labkit.sidebar import sidebar_section

FET_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_BATCH_KEY = "fet_active_batch"
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


def choose_batch() -> str | None:
    """Sidebar section 1: pick the batch. Returns None when there is none yet."""
    batches = list_batches()
    with sidebar_section("1) Run"):
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


def filters(frame: pd.DataFrame, groups: list[str], default_statuses: tuple[str, ...] = ("valid", "attention")) -> pd.DataFrame:
    """Sidebar section 2: sweep direction, status, group, rejected rows."""
    sweeps = list(dict.fromkeys(frame["sweep"]))
    statuses = [s for s in STATUS_ORDER if s in set(frame["status"])]
    with sidebar_section("2) Filters"):
        chosen_sweeps = st.multiselect("Sweep direction", sweeps, default=sweeps[:1], key="fet_filter_sweeps")
        chosen_statuses = st.multiselect(
            "Status",
            statuses,
            default=[s for s in default_statuses if s in statuses] or statuses,
            key=f"fet_filter_status_{'_'.join(default_statuses)}",
        )
        chosen_groups = st.multiselect("Groups", groups, default=groups, key="fet_filter_groups")
        show_rejected = st.checkbox("Show rejected sweeps", value=False, key="fet_filter_rejected")
    mask = frame["sweep"].isin(chosen_sweeps) & frame["status"].isin(chosen_statuses) & frame["group_display"].isin(chosen_groups)
    if not show_rejected:
        mask &= frame["decision"] != "rejected"
    return frame[mask]


def stop_if_empty(frame: pd.DataFrame) -> None:
    if frame.empty:
        st.info("No sweeps match the filters in the sidebar.")
        st.stop()
