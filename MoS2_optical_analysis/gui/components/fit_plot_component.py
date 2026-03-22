"""Reusable plotting components for fit results."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from .plot_theme import apply_plotly_theme

apply_plotly_theme()


def render_metric_histogram(df: pd.DataFrame, metric: str, title: str | None = None) -> None:
    if df.empty or metric not in df.columns:
        st.info(f"No data for metric: {metric}")
        return

    fig = px.histogram(
        df,
        x=metric,
        nbins=30,
        color="selected_model" if "selected_model" in df.columns else None,
        barmode="overlay",
        opacity=0.7,
        title=title or f"{metric} distribution",
    )
    st.plotly_chart(fig, width="stretch")


def render_map_scatter(df: pd.DataFrame, value_col: str, title: str) -> None:
    required = {"map_x", "map_y", value_col}
    if df.empty or not required.issubset(df.columns):
        st.info("Map columns are missing. Need map_x/map_y and selected value.")
        return

    plot_df = df.dropna(subset=["map_x", "map_y", value_col]).copy()
    if plot_df.empty:
        st.info("No valid points after dropping NaN map coordinates/values.")
        return

    fig = px.scatter(
        plot_df,
        x="map_x",
        y="map_y",
        color=value_col,
        hover_data=["spectrum_id", "selected_model"] if "selected_model" in plot_df.columns else ["spectrum_id"],
        color_continuous_scale="Viridis",
        title=title,
    )
    fig.update_traces(marker={"size": 14, "line": {"width": 0.5, "color": "black"}})
    fig.update_layout(yaxis={"autorange": "reversed"})
    st.plotly_chart(fig, width="stretch")


