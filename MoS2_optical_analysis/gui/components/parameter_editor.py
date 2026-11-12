"""Manual parameter review/editing component."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from fitting.mos2_core.review.manual_overrides import upsert_manual_override

_EDITABLE_PARAM_COLS = (
    "pl_position",
    "pl_height",
    "pl_fwhm",
    "e2g_position",
    "a1g_position",
    "delta_e2g_a1g",
    "e2g_fwhm",
    "a1g_fwhm",
)


def render_parameter_editor(df: pd.DataFrame, key: str = "param_editor") -> pd.DataFrame:
    if df.empty:
        st.info("No spectra rows available for editing.")
        return df

    editable_cols = [
        col
        for col in [
            "pl_position",
            "pl_height",
            "pl_fwhm",
            "e2g_position",
            "a1g_position",
            "delta_e2g_a1g",
            "e2g_fwhm",
            "a1g_fwhm",
            "review_decision",
        ]
        if col in df.columns
    ]
    col_config = {
        "review_decision": st.column_config.SelectboxColumn(
            "review_decision",
            help="Manual decision",
            options=["auto", "approved", "refit", "rejected"],
            required=True,
        )
    }

    edited = st.data_editor(
        df,
        width="stretch",
        num_rows="fixed",
        disabled=[c for c in df.columns if c not in editable_cols],
        column_config=col_config,
        key=key,
    )
    return edited


def apply_table_edits_to_report(
    original: pd.DataFrame,
    edited: pd.DataFrame,
    report_path: Path,
) -> int:
    if original.empty or edited.empty or list(original.columns) != list(edited.columns):
        return 0
    changed_mask = (original.fillna("__NA__") != edited.fillna("__NA__")).any(axis=1)
    changed_rows = edited[changed_mask]
    if changed_rows.empty:
        return 0

    applied = 0
    for idx, row in changed_rows.iterrows():
        spectrum_id = str(row.get("spectrum_id", "")).strip()
        if not spectrum_id:
            continue
        orig_row = original.loc[idx] if idx in original.index else row
        param_updates: dict[str, Any] = {}
        for col in _EDITABLE_PARAM_COLS:
            if col in edited.columns and pd.notna(row.get(col)):
                if pd.isna(orig_row.get(col)) or float(row[col]) != float(orig_row[col]):
                    param_updates[col] = float(row[col])
        decision = str(row.get("review_decision", "")).strip() if "review_decision" in edited.columns else None
        selected_model = str(row.get("selected_model", "")).strip()
        upsert_manual_override(
            report_json=report_path,
            spectrum_id=spectrum_id,
            action_type="flagged_table_edit",
            selected_model=selected_model,
            params=param_updates if param_updates else None,
            operator_note="flagged_spectra_editor",
            review_decision=decision,
        )
        applied += 1
    return applied


def render_changes_download(
    original: pd.DataFrame,
    edited: pd.DataFrame,
    file_stem: str,
    report_path: Path | None = None,
) -> None:
    if original.empty or edited.empty:
        return
    if list(original.columns) != list(edited.columns):
        st.warning("Edited table schema changed; skipping change export.")
        return

    changed_mask = (original.fillna("__NA__") != edited.fillna("__NA__")).any(axis=1)
    changed_rows = edited[changed_mask]
    st.caption(f"Changed rows: {len(changed_rows)}")
    if changed_rows.empty:
        return

    if report_path is not None and st.button(
        "Apply Edits to Active Report",
        type="primary",
        use_container_width=True,
        key=f"apply_flagged_edits_{file_stem}",
    ):
        count = apply_table_edits_to_report(original, edited, report_path)
        if count > 0:
            st.success(f"Applied edits for {count} spectrum row(s) to report overrides.")
            st.rerun()

    st.download_button(
        label="Download edited rows (CSV)",
        data=changed_rows.to_csv(index=False).encode("utf-8"),
        file_name=f"{file_stem}_edited_rows.csv",
        mime="text/csv",
    )
    st.download_button(
        label="Download edited rows (JSON)",
        data=json.dumps(changed_rows.to_dict(orient="records"), indent=2).encode("utf-8"),
        file_name=f"{file_stem}_edited_rows.json",
        mime="application/json",
    )


