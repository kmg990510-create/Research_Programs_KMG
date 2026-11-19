"""Shared window chrome, header/sidebar shell, and stage navigation for all lab programs.

This module owns the only DOM-dependent CSS selectors in the repository so the
fixed top bar, sidebar offset, card headings, and narrow-screen wrapping behave
consistently across standalone and unified runs. No measurement logic lives here.
"""

from __future__ import annotations

from collections.abc import Sequence
import html
from typing import Any

import streamlit as st

from labkit.sidebar import sidebar_section

UNIFIED_MODE_KEY = "kmg_unified_mode"
HUB_PAGE_MAP_KEY = "kmg_hub_page_map"
ACTIVE_PROGRAM_KEY = "hub_active_program"

PROGRAMS: tuple[tuple[str, str, str], ...] = (
    ("hub", "Program Hub", "grid_view"),
    ("mos2", "Optical Analysis", "show_chart"),
    ("fet", "FET Analysis", "memory"),
    ("ads", "Adsorption Sim", "hub"),
)

_CHROME_CSS = """
<style>
.st-key-kmg_masthead {
  position: fixed; inset: 0 0 auto; height: 3rem; z-index: 999990;
  box-sizing: border-box; background: #14273b; padding: 0 1.25rem; color: #fff;
  display: flex; align-items: center; justify-content: space-between;
  font-size: .8rem; min-width: 0; gap: .6rem;
}
[data-testid="stHeader"] { top: 3rem; background: transparent; pointer-events: none; }
[data-testid="stHeader"] * { pointer-events: auto; }
[data-testid="stSidebar"] { top: 3rem; height: calc(100dvh - 3rem); }
[data-testid="stSidebarCollapseButton"], [data-testid="stExpandSidebarButton"] { margin-top: .15rem; }
[data-testid="stMainBlockContainer"] { padding-top: 4.1rem; }
.kmg-brand { font-size: .98rem; color: #fff; font-weight: 700; white-space: nowrap; }
.kmg-status { color: #d3e3eb; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kmg-panel-title { margin: 0 0 .35rem; font-size: .97rem; color: #14273b; font-weight: 700; }
.kmg-card-hint {
  min-height: 2.75em; margin: 0 0 .5rem; font-size: .875rem;
  color: #46596d; line-height: 1.38;
}
.kmg-card-meta {
  min-height: 3.1em; margin: 0 0 .6rem; font-size: .82rem;
  color: #14273b; background: #f2f6fa; border: 1px solid #d9e4ee;
  border-radius: 6px; padding: .45rem .6rem; line-height: 1.35;
}
@media (max-width: 1180px) {
  .st-key-kmg_review_workspace > div > [data-testid="stHorizontalBlock"] {
    flex-wrap: wrap;
  }
  .st-key-kmg_review_workspace > div > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(1) {
    flex: 1 1 250px !important; min-width: 240px !important;
  }
  .st-key-kmg_review_workspace > div > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) {
    flex: 2 1 440px !important; min-width: 340px !important;
  }
  .st-key-kmg_review_workspace > div > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(3) {
    flex: 1 1 100% !important; min-width: 100% !important;
  }
  .st-key-kmg_curves_pair > div > [data-testid="stHorizontalBlock"] {
    flex-wrap: wrap;
  }
  .st-key-kmg_curves_pair > div > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
    flex: 1 1 320px !important; min-width: 280px !important;
  }
}
@media (max-width: 820px) {
  .st-key-kmg_hub_cards > div > [data-testid="stHorizontalBlock"] {
    flex-wrap: wrap;
  }
  .st-key-kmg_hub_cards > div > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
    flex: 1 1 100% !important; min-width: 100% !important;
  }
}
</style>
"""


def is_unified_mode() -> bool:
    """Return True when the page is running inside the unified root ``app.py``."""
    return bool(st.session_state.get(UNIFIED_MODE_KEY, False))


def sidebar_section_label(offset: int, name: str) -> str:
    """Number a sidebar section, shifting by +1 when ``1) Program`` is present."""
    number = offset + (1 if is_unified_mode() else 0)
    return f"{number}) {name}"


def render_masthead(status_text: str = "") -> None:
    """Render the fixed full-width top bar and layout CSS."""
    safe_status = html.escape(status_text) if status_text else ""
    right_html = f'<span class="kmg-status">{safe_status}</span>' if safe_status else ""
    st.html(
        f"""
        {_CHROME_CSS}
        <div class="st-key-kmg_masthead">
          <span class="kmg-brand">Research Programs KMG</span>
          {right_html}
        </div>
        """
    )


def panel_title(title: str) -> None:
    """Compact bold heading used at the top of bordered cards."""
    st.html(f'<div class="kmg-panel-title">{html.escape(title)}</div>')


def render_program_switcher(active_program: str) -> str | None:
    """Sidebar ``1) Program`` selector used by the unified entrypoint. Returns clicked id."""
    clicked: str | None = None
    with sidebar_section("1) Program", expanded=True):
        for program_id, label, icon in PROGRAMS:
            if st.button(
                label,
                icon=f":material/{icon}:",
                width="stretch",
                type="primary" if active_program == program_id else "secondary",
                key=f"kmg_nav_{program_id}",
            ):
                clicked = program_id
    return clicked


def resolve_page(program_id: str, stage_key: str, standalone_target: str) -> Any:
    """Resolve a target suitable for ``st.switch_page`` in both unified and standalone modes."""
    if is_unified_mode():
        page_map = st.session_state.get(HUB_PAGE_MAP_KEY, {})
        if (program_id, stage_key) in page_map:
            return page_map[(program_id, stage_key)]
    return standalone_target


def render_stage_header(
    program_title: str,
    stages: Sequence[tuple[str, Any]],
    active_stage: str,
    *,
    key_prefix: str,
) -> None:
    """Render the program title and top workflow stage switcher."""
    st.title(program_title)
    labels = [label for label, _ in stages]
    targets = {label: target for label, target in stages}
    widget_key = f"{key_prefix}_{active_stage}"
    if st.session_state.get(widget_key) not in labels:
        st.session_state[widget_key] = active_stage
    chosen = st.segmented_control(
        "Workflow",
        options=labels,
        key=widget_key,
        label_visibility="collapsed",
    )
    if chosen and chosen != active_stage and chosen in targets:
        st.switch_page(targets[chosen])


def render_subnav(
    label: str,
    options: Sequence[tuple[str, Any]],
    active_option: str,
    *,
    key_prefix: str,
) -> None:
    """Render secondary mode navigation within a stage (e.g. Spectra vs Map)."""
    labels = [opt for opt, _ in options]
    targets = {opt: target for opt, target in options}
    widget_key = f"{key_prefix}_{active_option}"
    if st.session_state.get(widget_key) not in labels:
        st.session_state[widget_key] = active_option
    chosen = st.segmented_control(
        label,
        options=labels,
        key=widget_key,
        label_visibility="collapsed",
    )
    if chosen and chosen != active_option and chosen in targets:
        st.switch_page(targets[chosen])
