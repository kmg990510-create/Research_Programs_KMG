"""Sidebar layout rule shared by the lab programs.

Every page builds its sidebar only from numbered, collapsible sections; no
widget sits outside a section.
"""

from __future__ import annotations

import streamlit as st


def sidebar_section(title: str, expanded: bool = True):
    """A numbered sidebar section, e.g. ``sidebar_section("2) Filters")``."""
    return st.sidebar.expander(title, expanded=expanded)
