"""Bulk review edits made from the Map Viewer. No Streamlit import."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from fitting.mos2_core.review.manual_overrides import upsert_manual_override

REVIEW_DECISIONS = ("approved", "refit", "rejected", "auto")
ACTION_TYPE = "map_viewer_edit"


def selected_ids_from_event(event: Any) -> list[str]:
    """Spectrum ids from a Streamlit Plotly selection event (customdata[0])."""
    try:
        points = event["selection"]["points"]
    except (KeyError, TypeError):
        return []
    ids: list[str] = []
    for point in points or []:
        custom = point.get("customdata") if isinstance(point, dict) else None
        if isinstance(custom, (list, tuple)) and custom:
            spectrum_id = str(custom[0])
            if spectrum_id and spectrum_id not in ids:
                ids.append(spectrum_id)
    return ids


def apply_decision(
    report_path: Path,
    frame: pd.DataFrame,
    spectrum_ids: Iterable[str],
    decision: str,
    note: str = "",
) -> int:
    """Record ``decision`` for each spectrum in the manual-overrides JSON.

    The fit report itself is not modified.
    """
    if decision not in REVIEW_DECISIONS:
        raise ValueError(f"Unknown review decision: {decision}")
    by_id = frame.assign(_sid=frame["spectrum_id"].astype(str)).set_index("_sid")
    applied = 0
    for spectrum_id in spectrum_ids:
        if spectrum_id not in by_id.index:
            continue
        upsert_manual_override(
            report_json=report_path,
            spectrum_id=spectrum_id,
            action_type=ACTION_TYPE,
            selected_model=str(by_id.loc[spectrum_id].get("selected_model", "") or ""),
            operator_note=note or "map_viewer",
            review_decision=decision,
        )
        applied += 1
    return applied
