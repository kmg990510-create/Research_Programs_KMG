"""Figure style inputs of the Map Viewer and their saved presets.

The style lives in ``st.session_state`` under ``<prefix>_style_<field>`` so that
a change applies on the same run and a preset can replace every field at once.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pandas as pd
import streamlit as st

from .map_figure import (
    AXIS_MODES,
    COLORMAPS,
    RANGE_MODES,
    MapStyle,
    default_axis_labels,
    load_style_preset,
    physical_axis_usable,
    save_style_preset,
)

STYLE_FIELDS = tuple(asdict(MapStyle()).keys())


def style_key(prefix: str, name: str) -> str:
    return f"{prefix}_style_{name}"


def init_style_state(prefix: str, title: str, colorbar_title: str, context: object) -> None:
    """Defaults for every style field; the titles follow the map and parameter until the user edits them."""
    if st.session_state.get(f"{prefix}_title_context") != context:
        st.session_state[f"{prefix}_title_context"] = context
        st.session_state[style_key(prefix, "title")] = title
        st.session_state[style_key(prefix, "colorbar_title")] = colorbar_title
    for name, default in asdict(MapStyle()).items():
        st.session_state.setdefault(style_key(prefix, name), default)
    pending = st.session_state.pop(f"{prefix}_pending_style", None)  # a preset chosen on the previous run
    if pending is not None:
        for name, value in asdict(pending).items():
            st.session_state[style_key(prefix, name)] = value


def _on_axis_mode_change(prefix: str) -> None:
    """Reset the axis labels to match the chosen coordinate mode and unit."""
    probe = MapStyle(
        axis_mode=st.session_state[style_key(prefix, "axis_mode")],
        axis_unit=st.session_state[style_key(prefix, "axis_unit")],
    )
    labels = default_axis_labels(probe)
    st.session_state[style_key(prefix, "x_label")], st.session_state[style_key(prefix, "y_label")] = labels


def style_inputs(prefix: str, values: pd.Series, size_section: str) -> None:
    """Draw the style inputs. ``values``: the finite values of the shown parameter (for the manual range)."""

    def key(name: str) -> str:
        return style_key(prefix, name)

    c1, c2 = st.columns(2)
    c1.selectbox("Colormap", COLORMAPS, key=key("colormap"))
    c2.checkbox("Reverse colormap", key=key("reverse_colormap"))
    st.radio("Color range", RANGE_MODES, horizontal=True, key=key("range_mode"))
    manual_range = st.session_state[key("range_mode")] == "Manual"
    if manual_range and not values.empty and st.session_state[key("zmin")] is None:
        st.session_state[key("zmin")] = float(values.quantile(0.02))
        st.session_state[key("zmax")] = float(values.quantile(0.98))
    m1, m2 = st.columns(2)
    m1.number_input("Color min", format="%.4f", key=key("zmin"), disabled=not manual_range)
    m2.number_input("Color max", format="%.4f", key=key("zmax"), disabled=not manual_range)
    st.text_input("Title", key=key("title"))
    st.text_input("Colorbar title", key=key("colorbar_title"))
    st.radio(
        "Axis coordinates",
        AXIS_MODES,
        horizontal=True,
        key=key("axis_mode"),
        on_change=_on_axis_mode_change,
        args=(prefix,),
        help="Physical: the first and last scan points are placed at Start and End, evenly spaced in between.",
    )
    # Always drawn (disabled when unused): Streamlit drops the stored value of a
    # keyed widget on runs where the widget is not drawn.
    index_axes = st.session_state[key("axis_mode")] != "Physical"
    a1, a2, a3 = st.columns(3)
    a1.number_input("X start", format="%.3f", key=key("x_start"), disabled=index_axes)
    a2.number_input("X end", format="%.3f", key=key("x_end"), disabled=index_axes)
    a3.text_input("Unit", key=key("axis_unit"), on_change=_on_axis_mode_change, args=(prefix,), disabled=index_axes)
    a4, a5, _ = st.columns(3)
    a4.number_input("Y start", format="%.3f", key=key("y_start"), disabled=index_axes)
    a5.number_input("Y end", format="%.3f", key=key("y_end"), disabled=index_axes)
    l1, l2 = st.columns(2)
    l1.text_input("X label", key=key("x_label"))
    l2.text_input("Y label", key=key("y_label"))
    s1, s2 = st.columns(2)
    s1.number_input("Font size", min_value=8, max_value=28, step=1, key=key("font_size"))
    s2.number_input("Cell gap (px)", min_value=0, max_value=6, step=1, key=key("cell_gap_px"))
    v1, v2, v3 = st.columns(3)
    v1.checkbox("Show values", key=key("show_values"))
    v2.number_input("Decimals", min_value=0, max_value=6, step=1, key=key("value_decimals"))
    v3.checkbox("Y origin at top", key=key("y_origin_top"))
    st.caption(f"Width, height, grid and image format: sidebar section {size_section}.")


def current_style(prefix: str, height_px: int) -> MapStyle:
    """The style as it is set now. The height comes from the sidebar size inputs; the cell size follows it."""
    fields = {name: st.session_state[style_key(prefix, name)] for name in STYLE_FIELDS}
    return MapStyle(**{**fields, "height_px": height_px})


def preset_inputs(prefix: str, style: MapStyle, preset_dir: Path) -> None:
    """Save the current style under a name, or load a saved one (applied on the next run)."""
    if style.axis_mode == "Physical" and not physical_axis_usable(style):
        st.warning("Start and End must differ on both axes. Showing point index instead.")
    st.divider()
    presets = sorted(p.stem for p in preset_dir.glob("*.yaml")) if preset_dir.exists() else []
    p1, p2 = st.columns(2)
    name = p1.text_input("Preset name", value="my_map_style", key=f"{prefix}_preset_name").strip()
    if p1.button("Save preset", key=f"{prefix}_preset_save", width="stretch") and name:
        save_style_preset(preset_dir / f"{name}.yaml", style)
        st.toast(f"Saved preset: {name}")
        st.rerun()
    chosen = p2.selectbox("Saved presets", presets, key=f"{prefix}_preset_pick") if presets else None
    if p2.button("Load preset", key=f"{prefix}_preset_load", width="stretch", disabled=not presets) and chosen:
        st.session_state[f"{prefix}_pending_style"] = load_style_preset(preset_dir / f"{chosen}.yaml")
        st.rerun()
    st.caption("Use the camera button on the figure to download it.")
