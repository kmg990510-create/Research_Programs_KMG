"""Manual parameter review/editing component."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st


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


def render_changes_download(original: pd.DataFrame, edited: pd.DataFrame, file_stem: str) -> None:
    if original.empty or edited.empty:
        return
    if list(original.columns) != list(edited.columns):
        st.warning("Edited table schema changed; skipping change export.")
        return

    changed_mask = (original != edited).any(axis=1)
    changed_rows = edited[changed_mask]
    st.caption(f"Changed rows: {len(changed_rows)}")
    if changed_rows.empty:
        return

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


