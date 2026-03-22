"""Tabular review component for spectra quality triage."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def render_review_table(df: pd.DataFrame, title: str = "Review Table") -> None:
    st.subheader(title)
    if df.empty:
        st.info("No rows to display.")
        return

    preferred_cols = [
        "spectrum_id",
        "map_x",
        "map_y",
        "selected_model",
        "fit_status",
        "e2g_position",
        "a1g_position",
        "delta_e2g_a1g",
        "prefit_e2g_snr",
        "prefit_a1g_snr",
        "rmse",
        "r2",
        "aic",
        "bic",
        "attention_score",
        "needs_attention",
        "invalid_reasons",
        "attention_reasons",
        "quality_flags",
        "review_decision",
    ]
    cols = [c for c in preferred_cols if c in df.columns]
    table = (df[cols] if cols else df).copy()
    if "quality_flags" in table.columns:
        table["quality_flags"] = table["quality_flags"].apply(
            lambda v: ", ".join(str(x) for x in v) if isinstance(v, list) else (str(v) if v is not None else "")
        )
    if "invalid_reasons" in table.columns:
        table["invalid_reasons"] = table["invalid_reasons"].apply(
            lambda v: ", ".join(str(x) for x in v) if isinstance(v, list) else (str(v) if v is not None else "")
        )
    if "attention_reasons" in table.columns:
        table["attention_reasons"] = table["attention_reasons"].apply(
            lambda v: ", ".join(str(x) for x in v) if isinstance(v, list) else (str(v) if v is not None else "")
        )
    st.dataframe(table, width="stretch", height=520)


