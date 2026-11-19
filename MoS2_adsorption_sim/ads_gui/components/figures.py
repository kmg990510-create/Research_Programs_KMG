"""Plotly figures for MoS2_adsorption_sim built strictly with labkit.plot_theme. No Streamlit import."""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ads_core.pipeline import BatchRun
from ads_core.report.summary import metric_label
from ads_core.simulation.md import MdStep
from ads_core.simulation.relax import BindingCurveResult, TrajectoryStep
from labkit.plot_theme import (
    AUX,
    DATA,
    FIT,
    LEGEND_INSIDE,
    LEGEND_RIGHT,
    LINE_AUX,
    LINE_DATA,
    LINE_FIT,
    MARK,
    MARKER_CENTER,
    MARKER_ON_LINE,
    MARKER_RAW,
    SEQUENTIAL,
    STATUS_COLORS,
    SURFACE,
    apply_paper_layout,
    categorical_colors,
)

GALLERY_MARGIN_WIDTH_PX = 74
GALLERY_MARGIN_HEIGHT_PX = 94


def gallery_size(panel_count: int, columns: int, panel_width_px: int | None, panel_height_px: int) -> tuple[int | None, int]:
    """Total gallery width and height computed from single-panel dimensions."""
    columns = max(1, min(columns, max(1, panel_count)))
    rows = -(-max(1, panel_count) // columns)
    width = None if panel_width_px is None else panel_width_px * columns + GALLERY_MARGIN_WIDTH_PX
    return width, panel_height_px * rows + GALLERY_MARGIN_HEIGHT_PX


def convergence_figure(
    steps: Sequence[TrajectoryStep],
    fmax_target: float,
    height: int = 440,
) -> go.Figure:
    """Two-row relaxation convergence figure: relative energy Delta-E (eV) and log fmax (eV/A)."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.10, row_heights=[0.52, 0.48])

    if steps:
        x = [s.step for s in steps]
        e0 = float(steps[0].energy_eV)
        de = [float(s.energy_eV) - e0 for s in steps]
        fmax_vals = [max(float(s.fmax_eV_per_A), 1e-6) for s in steps]

        fig.add_trace(
            go.Scatter(
                x=x,
                y=de,
                mode="lines+markers",
                name="ΔE (eV)",
                line={"color": DATA, "width": LINE_DATA},
                marker={"size": MARKER_ON_LINE, "color": DATA},
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=x,
                y=fmax_vals,
                mode="lines+markers",
                name="fmax (eV/Å)",
                line={"color": DATA, "width": LINE_DATA},
                marker={"size": MARKER_ON_LINE, "color": DATA},
            ),
            row=2,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=[x[0], x[-1]],
                y=[fmax_target, fmax_target],
                mode="lines",
                name=f"Target fmax ({fmax_target:g} eV/Å)",
                line={"color": FIT, "width": LINE_FIT, "dash": "dash"},
            ),
            row=2,
            col=1,
        )

    apply_paper_layout(fig, height=height)
    fig.update_yaxes(title_text="ΔE (eV)", automargin=True, row=1, col=1)
    fig.update_yaxes(title_text="fmax (eV/Å)", type="log", exponentformat="power", automargin=True, row=2, col=1)
    fig.update_xaxes(title_text="Optimization step", row=2, col=1)
    fig.update_layout(title_text="Relaxation convergence", legend=LEGEND_INSIDE, margin={"l": 72})
    return fig


def gallery_figure(panels: list[dict], columns: int = 4, row_height: int = 200) -> go.Figure:
    """Clickable grid of pose relaxation energy profiles colored by quality status.

    Each entry in ``panels`` holds ``pose_id``, ``title``, ``steps``, ``energies``,
    ``status``, ``rejected``, and ``e_ads_eV``.
    """
    if not panels:
        fig = go.Figure()
        apply_paper_layout(fig, font_size=11, height=row_height + GALLERY_MARGIN_HEIGHT_PX)
        return fig
    columns = max(1, min(columns, len(panels)))
    rows = -(-len(panels) // columns)
    fig = make_subplots(
        rows=rows,
        cols=columns,
        shared_xaxes=False,
        shared_yaxes=False,
        subplot_titles=[p["title"] for p in panels],
        horizontal_spacing=0.05,
        vertical_spacing=min(0.10, 0.5 / max(1, rows)),
    )
    for index, panel in enumerate(panels):
        rejected = bool(panel["rejected"])
        status = str(panel["status"])
        color = AUX if rejected else STATUS_COLORS[status]
        e_text = f"{panel['e_ads_eV']:.3f} eV" if panel["e_ads_eV"] is not None else "-"
        fig.add_trace(
            go.Scatter(
                x=panel["steps"],
                y=panel["energies"],
                mode="lines+markers",
                marker={"size": 6, "opacity": 0},
                meta=panel["pose_id"],
                line={"color": color, "width": LINE_DATA, "dash": "dot" if rejected else "solid"},
                hovertemplate=f"{panel['pose_id']}<br>Step=%{{x}}<br>ΔE=%{{y:.3f}} eV<br>E_ads={e_text}<extra></extra>",
                showlegend=False,
            ),
            row=index // columns + 1,
            col=index % columns + 1,
        )
        fig.layout.annotations[index].update(font={"size": 11, "color": STATUS_COLORS[status]})

    apply_paper_layout(fig, font_size=11, height=row_height * rows + GALLERY_MARGIN_HEIGHT_PX)
    fig.update_layout(margin={"l": 64, "r": 12, "t": 44, "b": 54}, dragmode="zoom", hovermode="closest", hoverdistance=-1)
    fig.add_annotation(text="Step", xref="paper", yref="paper", x=0.5, y=0, yshift=-40, showarrow=False, font={"size": 13})
    fig.add_annotation(text="ΔE (eV)", xref="paper", yref="paper", x=0, y=0.5, xshift=-52, textangle=-90, showarrow=False, font={"size": 13})
    return fig


def metric_figure(
    frame: pd.DataFrame,
    metric: str,
    groups: list[str],
    colors: dict[str, str],
    height: int = 420,
) -> go.Figure:
    """Box plot over included poses plus all points (hollow for invalid or rejected)."""
    fig = go.Figure()
    rng = np.random.default_rng(0)
    for index, group in enumerate(groups):
        part = frame[frame["group_display"] == group]
        used = pd.to_numeric(part.loc[part["included"], metric], errors="coerce").dropna()
        unused = part.loc[~part["included"]]
        unused_vals = pd.to_numeric(unused[metric], errors="coerce").dropna()

        if not used.empty:
            fig.add_trace(
                go.Box(
                    x=[index] * len(used),
                    y=used,
                    name=group,
                    boxpoints=False,
                    width=0.5,
                    line={"color": colors[group], "width": LINE_DATA},
                    fillcolor="rgba(0,0,0,0)",
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=index + rng.uniform(-0.16, 0.16, len(used)),
                    y=used,
                    mode="markers",
                    name=group,
                    marker={"size": MARKER_RAW, "color": colors[group], "line": {"color": SURFACE, "width": 1}},
                    text=part.loc[used.index, "pose_id"],
                    hovertemplate="%{text}<br>%{y:.4g}<extra></extra>",
                    showlegend=False,
                )
            )
        if not unused_vals.empty:
            fig.add_trace(
                go.Scatter(
                    x=index + rng.uniform(-0.16, 0.16, len(unused_vals)),
                    y=unused_vals,
                    mode="markers",
                    name="not in statistics",
                    marker={"size": MARKER_RAW, "symbol": "circle-open", "color": colors[group], "line": {"width": 1.5}},
                    text=unused.loc[unused_vals.index, "pose_id"],
                    hovertemplate="%{text}<br>%{y:.4g}<br>not in statistics<extra></extra>",
                    showlegend=False,
                )
            )

    apply_paper_layout(fig, height=height)
    fig.update_xaxes(tickmode="array", tickvals=list(range(len(groups))), ticktext=groups, range=[-0.6, max(0.4, len(groups) - 0.4)], ticks="")
    fig.update_yaxes(title_text=metric_label(metric), exponentformat="power")
    return fig


def energy_decomposition_figure(
    summary_df: pd.DataFrame,
    mode: str = "umlip_vs_d3",
    height: int = 440,
) -> go.Figure:
    """Grouped bar chart of E_ads decomposition at each group's lowest-energy pose."""
    fig = go.Figure()
    if not summary_df.empty:
        x = summary_df["group_display"].tolist()
        if mode == "int_vs_def":
            def_total = pd.to_numeric(summary_df["e_def_slab_at_best_eV"], errors="coerce").fillna(0.0) + pd.to_numeric(
                summary_df["e_def_mol_at_best_eV"], errors="coerce"
            ).fillna(0.0)
            traces = [
                ("E_int (interaction)", summary_df["e_int_at_best_eV"], FIT),
                ("E_def (slab + mol)", def_total, MARK),
                ("E_ads (total)", summary_df["e_ads_min_eV"], DATA),
            ]
        else:
            traces = [
                ("E_ads (uMLIP)", summary_df["e_ads_umlip_at_best_eV"], AUX),
                ("E_ads (DFT-D3)", summary_df["e_ads_d3_at_best_eV"], FIT),
                ("E_ads (total)", summary_df["e_ads_min_eV"], DATA),
            ]

        for name, vals, color in traces:
            fig.add_trace(go.Bar(x=x, y=pd.to_numeric(vals, errors="coerce"), name=name, marker_color=color))

    apply_paper_layout(fig, height=height)
    fig.update_layout(barmode="group", title_text="Energy decomposition (best pose per group)", legend=LEGEND_RIGHT)
    fig.update_yaxes(title_text="Energy (eV)")
    fig.update_xaxes(title_text="Group")
    return fig


def binding_curves_figure(
    curves: Sequence[BindingCurveResult],
    selected_idx: int | None = 0,
    height: int = 440,
) -> go.Figure:
    """Plot 1D E_ads(dz) binding curves: single curve decomposition (uMLIP + D3) or multi-curve total comparison."""
    fig = go.Figure()
    all_z: list[float] = []

    if curves and selected_idx is None:
        base_keys = [(c.surface_id, c.molecule_id, c.site_type) for c in curves]
        include_calc = len(set(base_keys)) < len(base_keys)
        labels = [
            f"{c.surface_id} | {c.molecule_id} ({c.site_type}) [{c.calculator_id}]"
            if include_calc
            else f"{c.surface_id} | {c.molecule_id} ({c.site_type})"
            for c in curves
        ]
        colors = categorical_colors(labels)
        well_legend_shown = False
        for c, label in zip(curves, labels):
            z = [p.dz_A for p in c.points]
            e = [p.e_ads_total_eV for p in c.points]
            all_z.extend(z)
            fig.add_trace(
                go.Scatter(
                    x=z,
                    y=e,
                    mode="lines+markers",
                    name=label,
                    line={"color": colors[label], "width": LINE_DATA},
                    marker={"size": MARKER_ON_LINE},
                )
            )
            if c.has_attractive_well and c.dz_eq_A is not None and c.e_min_total_eV is not None:
                fig.add_trace(
                    go.Scatter(
                        x=[c.dz_eq_A],
                        y=[c.e_min_total_eV],
                        mode="markers",
                        name="Equilibrium well",
                        legendgroup="eq_well",
                        showlegend=not well_legend_shown,
                        marker={"size": MARKER_CENTER + 2, "symbol": "diamond", "color": MARK},
                        hovertemplate=(
                            f"{label}<br>Δz_eq=%{{x:.2f}} Å<br>E_min=%{{y:.3f}} eV<extra></extra>"
                        ),
                    )
                )
                well_legend_shown = True
    elif curves:
        c = curves[min(selected_idx, len(curves) - 1)]
        z = [p.dz_A for p in c.points]
        all_z.extend(z)
        fig.add_trace(
            go.Scatter(
                x=z,
                y=[p.e_ads_total_eV for p in c.points],
                mode="lines+markers",
                name="Total E_ads",
                line={"color": DATA, "width": LINE_DATA},
                marker={"size": MARKER_ON_LINE},
            )
        )
        fig.add_trace(
            go.Scatter(
                x=z,
                y=[p.e_ads_umlip_eV for p in c.points],
                mode="lines+markers",
                name="uMLIP only",
                line={"color": AUX, "width": LINE_DATA, "dash": "dot"},
                marker={"size": MARKER_ON_LINE},
            )
        )
        d3_vals = [p.e_ads_d3_eV for p in c.points if p.e_ads_d3_eV is not None]
        if len(d3_vals) == len(c.points):
            fig.add_trace(
                go.Scatter(
                    x=z,
                    y=d3_vals,
                    mode="lines+markers",
                    name="DFT-D3 dispersion",
                    line={"color": FIT, "width": LINE_FIT, "dash": "dash"},
                    marker={"size": MARKER_ON_LINE},
                )
            )
        if c.has_attractive_well and c.dz_eq_A is not None and c.e_min_total_eV is not None:
            fig.add_trace(
                go.Scatter(
                    x=[c.dz_eq_A],
                    y=[c.e_min_total_eV],
                    mode="markers",
                    name=f"Equilibrium well (Δz={c.dz_eq_A:.2f} Å, E={c.e_min_total_eV:.3f} eV)",
                    marker={"size": MARKER_CENTER + 2, "symbol": "diamond", "color": MARK},
                    hovertemplate="Δz_eq=%{x:.2f} Å<br>E_min=%{y:.3f} eV<extra></extra>",
                )
            )

    if all_z:
        fig.add_trace(
            go.Scatter(
                x=[min(all_z), max(all_z)],
                y=[0.0, 0.0],
                mode="lines",
                name="Dissociation limit (0 eV)",
                line={"color": AUX, "width": LINE_AUX, "dash": "dot"},
            )
        )

    apply_paper_layout(fig, height=height)
    fig.update_xaxes(title_text="COM height above top S plane Δz (Å)")
    fig.update_yaxes(title_text="E_ads (eV)")
    fig.update_layout(title_text="1D E(z) Binding Curve", legend=LEGEND_INSIDE)
    return fig


def site_energy_map_figure(
    run: BatchRun,
    frame: pd.DataFrame,
    surface_id: str,
    height: int = 460,
) -> go.Figure:
    """2D xy surface map on one slab showing Mo/S lattice, defects, and relaxed pose E_ads."""
    fig = go.Figure()
    slab = run.slabs.get(surface_id)
    if slab is not None:
        tags = slab.atoms.get_tags()
        pos = slab.atoms.get_positions()
        mo_pos = pos[tags == 1]
        top_s_pos = pos[tags == 2]
        cell = np.array(slab.atoms.get_cell())
        o = np.zeros(2)
        a, b = cell[0, :2], cell[1, :2]
        box_x = [o[0], a[0], a[0] + b[0], b[0], o[0]]
        box_y = [o[1], a[1], a[1] + b[1], b[1], o[1]]
        fig.add_trace(
            go.Scatter(x=box_x, y=box_y, mode="lines", name="Supercell boundary", line={"color": AUX, "width": LINE_AUX, "dash": "dot"})
        )
        if len(mo_pos):
            fig.add_trace(
                go.Scatter(
                    x=mo_pos[:, 0],
                    y=mo_pos[:, 1],
                    mode="markers",
                    name="Mo lattice",
                    marker={"size": MARKER_RAW, "color": AUX, "symbol": "hexagon"},
                )
            )
        if len(top_s_pos):
            fig.add_trace(
                go.Scatter(
                    x=top_s_pos[:, 0],
                    y=top_s_pos[:, 1],
                    mode="markers",
                    name="Top S lattice",
                    marker={"size": MARKER_ON_LINE + 1, "color": AUX, "symbol": "circle-open"},
                )
            )
        if slab.defect_positions_A:
            fig.add_trace(
                go.Scatter(
                    x=[d[0] for d in slab.defect_positions_A],
                    y=[d[1] for d in slab.defect_positions_A],
                    mode="markers",
                    name=f"Defect ({slab.defect_type})",
                    marker={"size": MARKER_CENTER + 2, "color": MARK, "symbol": "x"},
                )
            )

    sub = frame[(frame["surface_id"] == surface_id) & frame["e_ads_eV"].notna()]
    if not sub.empty and slab is not None:
        from ase.geometry import find_mic

        xs_rel, ys_rel, vals, labels = [], [], [], []
        disp_x: list[float | None] = []
        disp_y: list[float | None] = []
        for row in sub.itertuples():
            art = run.artifacts.get(row.pose_id)
            if art is None:
                continue
            mol_pos = art.relaxed_atoms.positions[list(art.mol_indices)]
            masses = art.relaxed_atoms.get_masses()[list(art.mol_indices)]
            com_rel = np.sum(mol_pos * masses[:, None], axis=0) / np.sum(masses)
            # Minimum-image displacement from initial site to relaxed COM
            site_xy = np.array([art.site_xy_A[0], art.site_xy_A[1], 0.0])
            rel_v, _ = find_mic(
                np.array([[com_rel[0] - site_xy[0], com_rel[1] - site_xy[1], 0.0]]),
                cell=art.relaxed_atoms.cell,
                pbc=(True, True, False),
            )
            com_disp = site_xy[:2] + rel_v[0, :2]
            xs_rel.append(float(com_disp[0]))
            ys_rel.append(float(com_disp[1]))
            vals.append(float(row.e_ads_eV))
            labels.append(f"{row.molecule_id} · {row.site_type} ({row.orientation})")
            disp_x.extend([float(site_xy[0]), float(com_disp[0]), None])
            disp_y.extend([float(site_xy[1]), float(com_disp[1]), None])

        if disp_x:
            fig.add_trace(
                go.Scatter(
                    x=disp_x,
                    y=disp_y,
                    mode="lines",
                    name="Site -> Relaxed COM",
                    line={"color": AUX, "width": LINE_AUX},
                    hoverinfo="skip",
                )
            )
        if xs_rel:
            fig.add_trace(
                go.Scatter(
                    x=xs_rel,
                    y=ys_rel,
                    mode="markers",
                    name="Relaxed COM (E_ads)",
                    text=labels,
                    hovertemplate="%{text}<br>E_ads=%{marker.color:.3f} eV<extra></extra>",
                    marker={
                        "size": MARKER_CENTER,
                        "color": vals,
                        "colorscale": SEQUENTIAL,
                        "showscale": True,
                        "colorbar": {"title": {"text": "E_ads (eV)"}},
                        "line": {"color": DATA, "width": 1},
                    },
                )
            )

    apply_paper_layout(fig, height=height)
    fig.update_xaxes(title_text="x (Å)")
    fig.update_yaxes(title_text="y (Å)", scaleanchor="x", scaleratio=1)
    fig.update_layout(
        title={"text": f"Adsorption COM Map — {surface_id}", "y": 0.97, "yanchor": "top"},
        margin={"t": 170},
        legend={"orientation": "h", "y": 1.02, "yanchor": "bottom", "x": 0.0, "xanchor": "left", "font": {"size": 11}},
    )
    return fig


def md_trajectory_figure(
    steps: Sequence[MdStep],
    target_temp_K: float | None = None,
    cutoff_A: float | None = None,
    height: int = 440,
) -> go.Figure:
    """Two-row MD time-series figure: adsorbate COM height dz_com (A) and temperature (K)."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.10, row_heights=[0.54, 0.46])

    if steps:
        t_vals = [float(s.time_fs) for s in steps]
        dz_points = [(float(s.time_fs), float(s.dz_com_A)) for s in steps if s.dz_com_A is not None]
        if dz_points:
            fig.add_trace(
                go.Scatter(
                    x=[pt[0] for pt in dz_points],
                    y=[pt[1] for pt in dz_points],
                    mode="lines+markers",
                    name="dz_com (Å)",
                    line={"color": DATA, "width": LINE_DATA},
                    marker={"size": MARKER_ON_LINE, "color": DATA},
                ),
                row=1,
                col=1,
            )
        if cutoff_A is not None:
            fig.add_trace(
                go.Scatter(
                    x=[t_vals[0], t_vals[-1]],
                    y=[float(cutoff_A), float(cutoff_A)],
                    mode="lines",
                    name=f"Adsorption cutoff ({cutoff_A:g} Å)",
                    line={"color": FIT, "width": LINE_FIT, "dash": "dash"},
                ),
                row=1,
                col=1,
            )
        fig.add_trace(
            go.Scatter(
                x=t_vals,
                y=[float(s.temperature_K) for s in steps],
                mode="lines",
                name="Temperature (K)",
                line={"color": AUX, "width": LINE_DATA},
            ),
            row=2,
            col=1,
        )
        if target_temp_K is not None:
            fig.add_trace(
                go.Scatter(
                    x=[t_vals[0], t_vals[-1]],
                    y=[float(target_temp_K), float(target_temp_K)],
                    mode="lines",
                    name=f"Target T ({target_temp_K:g} K)",
                    line={"color": MARK, "width": LINE_FIT, "dash": "dash"},
                ),
                row=2,
                col=1,
            )

    apply_paper_layout(fig, height=height)
    fig.update_yaxes(title_text="dz_com (Å)", row=1, col=1)
    fig.update_yaxes(title_text="T (K)", row=2, col=1)
    fig.update_xaxes(title_text="Time (fs)", row=2, col=1)
    fig.update_layout(title_text="MD trajectory (height & temperature)", legend=LEGEND_INSIDE)
    return fig


def coverage_distance_summary_figure(overview_df: pd.DataFrame, height: int = 440) -> go.Figure:
    """Two-panel Plotly overview: shortest intermolecular contacts (top) and E_ads/mol split (bottom)."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.12, row_heights=[0.52, 0.48])
    if overview_df.empty:
        apply_paper_layout(fig, height=height)
        return fig

    x_labels = overview_df["case_id"].astype(str).tolist()
    contact_specs = [
        ("min_S_S_A", "min d(S···S)", "#d62728", "circle"),
        ("min_N_S_A", "min d(N···S)", "#1f77b4", "square"),
        ("min_heavy_A", "min d(Heavy···Heavy)", DATA, "diamond"),
        ("min_COM_A", "min d(COM···COM)", "#2ca02c", "triangle-up"),
    ]
    for col, label, color, symbol in contact_specs:
        if col in overview_df.columns:
            fig.add_trace(
                go.Scatter(
                    x=x_labels,
                    y=overview_df[col],
                    mode="lines+markers",
                    name=label,
                    line={"color": color, "width": LINE_DATA},
                    marker={"size": MARKER_ON_LINE + 2, "color": color, "symbol": symbol},
                ),
                row=1,
                col=1,
            )

    fig.add_trace(
        go.Bar(
            x=x_labels,
            y=overview_df["e_sub_per_mol_eV"],
            name="E_sub / mol (eV)",
            marker={"color": "#4c78a8"},
        ),
        row=2,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=x_labels,
            y=overview_df["e_lat_per_mol_eV"],
            name="E_lat / mol (eV)",
            marker={"color": "#f58518"},
        ),
        row=2,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x_labels,
            y=overview_df["e_ads_per_mol_eV"],
            mode="lines+markers",
            name="Total E_ads / mol (eV)",
            line={"color": DATA, "width": LINE_FIT},
            marker={"size": MARKER_ON_LINE + 1, "color": DATA},
        ),
        row=2,
        col=1,
    )

    apply_paper_layout(fig, height=height)
    fig.update_yaxes(title_text="Min distance (Å)", row=1, col=1)
    fig.update_yaxes(title_text="Energy / mol (eV)", row=2, col=1)
    fig.update_xaxes(tickangle=-25, row=2, col=1)
    fig.update_layout(
        title_text="N=1–4 Intermolecular Distances & Substrate/Lateral Decomposition",
        barmode="relative",
        legend=LEGEND_RIGHT,
    )
    return fig


def pair_distance_heatmap_figure(
    matrix: np.ndarray,
    mol_labels: Sequence[str],
    title: str,
    height: int = 340,
) -> go.Figure:
    """Annotated N x N molecule-to-molecule MIC distance heatmap (Å)."""
    text_vals = [[("" if np.isnan(v) or i == j else f"{v:.2f}") for j, v in enumerate(row)] for i, row in enumerate(matrix)]
    fig = go.Figure(
        data=go.Heatmap(
            z=matrix,
            x=list(mol_labels),
            y=list(mol_labels),
            colorscale=SEQUENTIAL,
            reversescale=True,
            text=text_vals,
            texttemplate="%{text} Å",
            colorbar={"title": {"text": "d (Å)"}},
            hovertemplate="%{y} ↔ %{x}: %{z:.2f} Å<extra></extra>",
        )
    )
    apply_paper_layout(fig, height=height)
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(title_text=title)
    return fig
