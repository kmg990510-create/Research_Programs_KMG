import math
from itertools import product

import plotly.graph_objects as go
import streamlit as st

INK = "#14273b"
TEAL = "#067674"
BLUE = "#547494"
AMBER = "#be791b"
TOOLS = ("Program Hub", "Optical Analysis", "FET Analysis", "Adsorption Sim")
ICONS = ("grid_view", "show_chart", "memory", "hub")

st.set_page_config(page_title="Research Programs KMG · Preview", layout="wide")
st.html("""
<style>
.st-key-kmg_masthead {
  position: fixed; inset: 0 0 auto; height: 3rem; z-index: 999990;
  box-sizing: border-box; background: #14273b; padding: 0 1.25rem; color: #fff;
  display: flex; align-items: center; justify-content: space-between;
  font-size: .8rem; min-width: 0; gap: .6rem;
}
[data-testid="stHeader"] { top: 3rem; background: transparent; }
[data-testid="stSidebar"] { top: 3rem; height: calc(100dvh - 3rem); }
[data-testid="stSidebarCollapseButton"], [data-testid="stExpandSidebarButton"] { margin-top: .15rem; }
.kmg-brand { font-size: .98rem; color: #fff; font-weight: 700; }
.kmg-preview { color: #d3e3eb; }
.kmg-stages { display:flex; flex-wrap:wrap; gap: .45rem 1.4rem;
  padding: 0; border-bottom: 1px solid #ced9e3; color: #46596d; }
.kmg-stages span { padding: .28rem .1rem .48rem; }
.kmg-stages [aria-current] { color: #067674; border-bottom: 2px solid #067674; font-weight: 700; }
.kmg-panel-title { margin: 0; font-size: .97rem; color: #14273b; font-weight: 700; }
</style>
<div class="st-key-kmg_masthead">
 <span class="kmg-brand">Research Programs KMG</span>
 <span class="kmg-preview">UI PREVIEW · Sample data</span>
</div>
""")


def open_tool(name):
    st.session_state["preview_page"] = name


def retain_widgets(*keys):
    for key in keys:
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]


st.session_state.setdefault("preview_stage", "Devices")
st.session_state.setdefault("preview_compare_view", "Statistics")
retain_widgets(
    "preview_batch", "preview_stage", "preview_groups", "preview_sweeps",
    "preview_status", "preview_compare_view", "preview_device",
)

with st.sidebar:
    with st.expander("1) Program", expanded=True):
        for name, icon in zip(TOOLS, ICONS):
            st.button(
                name, icon=f":material/{icon}:", width="stretch",
                type="primary" if st.session_state.get("preview_page", TOOLS[0]) == name else "secondary",
                key=f"preview_go_{name}", on_click=open_tool, args=(name,),
            )
    if st.session_state.get("preview_page") == "FET Analysis":
        with st.expander("2) Batch", expanded=True):
            st.selectbox("Active batch", ("260916", "260918"), key="preview_batch")
            st.caption("Sample data · Shared across FET stages")


def stage_bar(names, active):
    items = "".join(
        f'<span aria-current="page">{name}</span>' if name == active else f"<span>{name}</span>"
        for name in names
    )
    st.html(f'<div class="kmg-stages" aria-label="Workflow">{items}</div>')


def panel_title(title):
    st.html(f'<div class="kmg-panel-title">{title}</div>')


def plot(fig, x_title, y_title, *, height=270, log=False, legend=False):
    fig.update_layout(
        height=height, margin=dict(l=58, r=17, b=52, t=12),
        template="plotly_white", paper_bgcolor="white", plot_bgcolor="white",
        font=dict(family="Arial", size=13, color=INK), showlegend=legend,
        legend=dict(x=0.02, y=0.98, bgcolor="rgba(255,255,255,0.84)"),
    )
    axes = dict(mirror="allticks", showline=True, linecolor=INK, ticks="inside", showgrid=False, zeroline=False)
    fig.update_xaxes(title_text=x_title, **axes)
    fig.update_yaxes(title_text=y_title, type="log" if log else "linear", **axes)
    st.plotly_chart(fig, width="stretch", theme=None, config={"displayModeBar": False})


def spectrum(temp=300, miniature=False):
    centers = (1.875 + (300 - temp) * .00024, 2.015 + (300 - temp) * .00016)
    widths = (.029 + temp * .000033, .040 + temp * .000035)
    energies = [1.68 + .005 * i for i in range(112)]
    peaks = [
        [scale * math.exp(-.5 * ((energy - center) / width) ** 2) for energy in energies]
        for scale, center, width in zip((.68, .43), centers, widths)
    ]
    fit = [.035 + a + b for a, b in zip(*peaks)]
    fig = go.Figure(go.Scatter(x=energies, y=fit, name="Fit", line=dict(color=TEAL, width=2)))
    if not miniature:
        for label, peak, color in zip(("Peak 1", "Peak 2"), peaks, (BLUE, AMBER)):
            fig.add_scatter(x=energies, y=peak, name=label, line=dict(color=color, width=1.4, dash="dot"))
        fig.add_scatter(
            x=energies[::3], y=[v + .012 * math.sin(i * 1.9) for i, v in enumerate(fit[::3])],
            mode="markers", name="Sample", marker=dict(color=INK, size=4),
        )
    return fig, centers, widths


def transfer(index=0):
    gates = list(range(-40, 41))
    threshold = 5.5 + 2.6 * index
    currents = [10 ** (-11.5 + 6.1 / (1 + math.exp(-(gate - threshold) / 7.8))) for gate in gates]
    return go.Figure(go.Scatter(x=gates, y=currents, name="Forward sweep", line=dict(color=TEAL, width=2)))


def binding(site):
    depth, r_min = (.55, 2.2) if site == "Mo top" else (.31, 2.5)
    radii = [1.65 + i * .047 for i in range(85)]
    energies = [depth * ((1 - math.exp(-1.6 * (r - r_min))) ** 2 - 1) for r in radii]
    return go.Figure(go.Scatter(x=radii, y=energies, line=dict(color=TEAL, width=2)))


def structure(site="Mo top", *, height=385, compact=False):
    lattice = 3.15
    layer = [
        (lattice * (col + row / 2), lattice * .866 * row, 0)
        for row, col in product(range(3), range(5))
    ]
    sulfur = [(x + lattice / 2, y + lattice * .289, zoff) for (x, y, _), zoff in product(layer, (-1.46, 1.46))]
    base = layer[7] if site == "Mo top" else sulfur[15]
    adsorbate = [(base[0], base[1], 3.65), (base[0], base[1], 4.78)]
    bonds = [(mo, s) for mo, s in product(layer, sulfur) if math.dist(mo, s) < 2.47]
    bonds.append(tuple(adsorbate))
    xyz = [[value for bond in bonds for value in (bond[0][axis], bond[1][axis], None)] for axis in range(3)]
    fig = go.Figure(go.Scatter3d(
        x=xyz[0], y=xyz[1], z=xyz[2], mode="lines", hoverinfo="skip",
        line=dict(color="#9baab9", width=3),
    ))
    for name, positions, color, size in (
        ("Mo", layer, BLUE, 7), ("S", sulfur, "#d6a044", 6),
        ("C", adsorbate[:1], INK, 8), ("O", adsorbate[1:], "#c85550", 8),
    ):
        x, y, z = zip(*positions)
        fig.add_scatter3d(
            x=x, y=y, z=z, mode="markers", text=[name] * len(x),
            hovertemplate="%{text}<extra></extra>", marker=dict(color=color, size=size),
        )
    fig.update_layout(
        showlegend=False, height=height, margin=dict(l=0, r=0, b=0, t=0), paper_bgcolor="white",
        scene=dict(
            xaxis_visible=False, yaxis_visible=False, zaxis_visible=False,
            aspectmode="data", bgcolor="white",
            camera=dict(eye=dict(x=.7, y=-1.75, z=.95)),
        ),
    )
    st.plotly_chart(fig, width="stretch", theme=None, config={"displayModeBar": not compact})


GROUPS = ("INTL209", "INTL185", "INTL184")
GROUP_COLORS = dict(zip(GROUPS, (BLUE, AMBER, TEAL)))
QUANTITIES = ("Mobility (cm²/V·s)", "Vth (V)", "SS (mV/dec)", "log₁₀(on/off)")


def fet_rows(batch):
    rows = []
    for group_index, group in enumerate(GROUPS):
        for device_index, device in enumerate(("A5", "C1", "D3", "D6")):
            for sweep_index, sweep in enumerate(("Forward", "Reverse")):
                variation = (device_index - 1.5) * (1 + group_index / 3) + sweep_index * .7
                offset = 0 if batch == "260916" else .9
                rows.append({
                    "key": f"{group[-3:]} {device} · {sweep}",
                    "group": group,
                    "device": device,
                    "sweep": sweep,
                    "status": "Invalid" if device_index == 3 and sweep_index else "Attention" if device_index == 2 else "Valid",
                    "index": group_index * 1.3 + device_index * .4 + sweep_index * .35 + offset,
                    QUANTITIES[0]: (20, 26, 14)[group_index] + variation + offset,
                    QUANTITIES[1]: (19, 10, 3)[group_index] + variation + offset,
                    QUANTITIES[2]: (460, 850, 1200)[group_index] + 90 * variation + 50 * offset,
                    QUANTITIES[3]: (8.9, 8.7, 8.5)[group_index] + variation / 15 - offset / 20,
                })
    return rows


def compare_view(rows):
    st.header("Compare")
    main_controls, group_actions = st.columns([4, 1], vertical_alignment="bottom")
    view = main_controls.segmented_control(
        "Compare view", ("Statistics", "Overlay", "Summary table"),
        key="preview_compare_view", label_visibility="collapsed",
    ) or "Statistics"
    with group_actions.popover("Manage groups", width="stretch"):
        st.caption("Display labels and order for Compare")
        order = st.multiselect("Group order", GROUPS, default=GROUPS, key="preview_group_order")
        labels = {group: st.text_input(f"{group} display name", group, key=f"preview_label_{group}").strip() or group for group in GROUPS}
    order = [*order, *(group for group in GROUPS if group not in order)]
    saved = st.session_state.get("preview_decisions", {}).get(st.session_state["preview_batch"], {})
    eligible = [row for row in rows if row["status"] != "Invalid" and saved.get(row["key"]) != "Excluded"]
    if not rows:
        st.info("No sweeps match the current filters.")
        return

    if view == "Statistics":
        metrics, chart_controls = st.columns([4, 1], vertical_alignment="bottom")
        quantities = metrics.multiselect("Quantities", QUANTITIES, default=QUANTITIES, key="preview_quantities")
        with chart_controls.popover("Figure settings", width="stretch"):
            height = st.slider("Height (px)", 240, 470, 300, key="preview_stat_height")
            show_points = st.checkbox("Show individual sweeps", value=True, key="preview_stat_points")
        st.caption(f"{len(eligible)} of {len(rows)} matching sweeps in statistics · Invalid and excluded sweeps omitted")
        if not eligible or not quantities:
            st.info("Choose at least one quantity and include a sweep to show statistics.")
            return
        for index in range(0, len(quantities), 2):
            panels = st.columns(2) if index + 1 < len(quantities) else (st.container(),)
            for panel, quantity in zip(panels, quantities[index:index + 2]):
                with panel, st.container(border=True):
                    panel_title(quantity)
                    figure = go.Figure()
                    for group in order:
                        values = [row[quantity] for row in eligible if row["group"] == group]
                        if values:
                            figure.add_box(x=[labels[group]] * len(values), y=values, name=labels[group],
                                           boxpoints="all" if show_points else False,
                                           marker_color=GROUP_COLORS[group], line_color=GROUP_COLORS[group])
                    plot(figure, "Group", quantity, height=height)

    elif view == "Overlay":
        controls, chart_controls = st.columns([4, 1], vertical_alignment="bottom")
        scale = controls.segmented_control("Current axis scale", ("Linear", "Log"), default="Log", key="preview_overlay_scale")
        with chart_controls.popover("Figure settings", width="stretch"):
            height = st.slider("Height (px)", 280, 640, 410, key="preview_overlay_height")
        st.caption(f"{len(rows)} matching sweeps · Invalid and excluded sweeps appear muted")
        figure = go.Figure()
        for group in order:
            seen = False
            for row in (row for row in rows if row["group"] == group):
                trace = transfer(row["index"]).data[0]
                muted = row["status"] == "Invalid" or saved.get(row["key"]) == "Excluded"
                trace.update(name=labels[group], legendgroup=group, showlegend=not seen,
                             line=dict(color=GROUP_COLORS[group], dash="dot" if muted else "solid"),
                             opacity=.32 if muted else .85, hovertemplate=f"{row['key']}<br>%{{x}} V · %{{y:.2e}} A<extra></extra>")
                figure.add_trace(trace)
                seen = True
        with st.container(border=True):
            panel_title("Transfer Overlay")
            plot(figure, "Gate voltage (V)", "Drain current (A)", height=height, log=scale != "Linear", legend=True)

    else:
        st.caption(f"{len(rows)} matching sweeps · Included indicates membership in statistics")
        st.dataframe([
            {
                "Group": labels[group], "Device": row["device"], "Sweep": row["sweep"], "Status": row["status"],
                "Decision": saved.get(row["key"], "—"), "Included": row in eligible,
                **{quantity: round(row[quantity], 2) for quantity in QUANTITIES},
            }
            for group in order for row in rows if row["group"] == group
        ], hide_index=True, width="stretch")


def devices_view(rows):
    devices = tuple(row["key"] for row in rows)
    batch = st.session_state["preview_batch"]
    saved = st.session_state.setdefault("preview_decisions", {}).setdefault(batch, {})
    if st.session_state.get("preview_device") not in devices:
        st.session_state["preview_device"] = devices[0]

    def decide(choice):
        device_id = st.session_state["preview_device"]
        saved[device_id] = choice
        if choice != "Pending":
            st.session_state["preview_device"] = devices[(devices.index(device_id) + 1) % len(devices)]

    listing, chart, review = st.columns([1, 4, 1.6], gap="medium")
    with listing, st.container(border=True):
        panel_title("Devices")
        st.caption(f"{len(devices)} matching sweeps")
        with st.container(height=305, border=False):
            device = st.radio("Device", devices, key="preview_device", label_visibility="collapsed")
    row = rows[devices.index(device)]
    index = row["index"]
    with chart:
        st.caption(f"{row['group']} · {row['device']} · {row['sweep']} sweep")
        linear, log = st.columns(2)
        with linear, st.container(border=True):
            panel_title("Linear")
            plot(transfer(index), "Gate voltage (V)", "Drain current (A)", height=285)
        with log, st.container(border=True):
            panel_title("Log")
            plot(transfer(index), "Gate voltage (V)", "Drain current (A)", height=285, log=True)
    with review, st.container(border=True):
        panel_title("Review")
        st.markdown("**Vth (V)**　—  \n**Mobility (cm²/V·s)**　—  \n**SS (mV/dec)**　—")
        decision = saved.get(device, "Pending")
        if decision == "Pending":
            if row["status"] == "Valid":
                st.caption("Valid")
            elif row["status"] == "Invalid":
                st.error("Invalid")
            else:
                st.warning("Attention")
        else:
            st.info(decision)
        st.button("Approve", key="preview_approve", type="primary", width="stretch", on_click=decide, args=("Approved",))
        st.button("Exclude", key="preview_exclude", width="stretch", on_click=decide, args=("Excluded",))
        st.button("Clear", key="preview_clear", width="stretch", on_click=decide, args=("Pending",), disabled=decision == "Pending")


page = st.session_state.get("preview_page", TOOLS[0])

if page == "Program Hub":
    st.title("Program Hub")
    st.caption("Select a program to open its workspace.")
    cards = st.columns(3, gap="medium")
    for card, name, title, hint in zip(
        cards, TOOLS[1:],
        ("MoS₂ Optical Analysis", "FET Analysis", "MoS₂ Adsorption Sim"),
        ("Raman and PL spectra", "Transfer curves and device review", "Structure viewer and adsorption energies"),
    ):
        with card, st.container(border=True):
            panel_title(title)
            st.caption(hint)
            if name == "Optical Analysis":
                plot(spectrum(miniature=True)[0], "Energy (eV)", "Intensity (a.u.)", height=182)
            elif name == "FET Analysis":
                plot(transfer(), "Gate voltage (V)", "Drain current (A)", height=182, log=True)
            else:
                structure(height=182, compact=True)
            st.button("Open", icon=":material/arrow_forward:", width="stretch", key=f"preview_card_{name}", on_click=open_tool, args=(name,))
    with st.container(border=True):
        panel_title("Data Sources")
        st.table([
            {"Data source": "PL spectra", "Format": "ASC", "Contents": "Energy and intensity"},
            {"Data source": "BG transfer", "Format": "CSV", "Contents": "Gate voltage and drain current"},
            {"Data source": "Adsorption poses", "Format": "XYZ", "Contents": "Atomic coordinates"},
        ])

elif page == "Optical Analysis":
    st.title("Spectra Viewer")
    stage_bar(("Run", "Review", "Viewer", "Compare", "Finalize"), "Viewer")
    selection = st.segmented_control("Temperature (K)", options=[77, 150, 200, 300], default=300, key="preview_temp")
    temp = selection or 300
    figure, centers, widths = spectrum(temp)
    chart, details = st.columns([2, 1], gap="medium")
    with chart, st.container(border=True):
        panel_title("Photoluminescence")
        plot(figure, "Energy (eV)", "Intensity (a.u.)", height=355, legend=True)
    with details, st.container(border=True):
        panel_title("Peak Fit")
        st.caption(f"Pristine MoS₂ · {temp} K")
        st.table([
            {"Peak": i, "Energy (eV)": f"{center:.3f}", "FWHM (eV)": f"{2.355 * width:.3f}"}
            for i, (center, width) in enumerate(zip(centers, widths), 1)
        ])
        st.caption("Simulated spectrum")

elif page == "FET Analysis":
    st.title("FET Analysis")
    selected_stage = st.segmented_control(
        "Workflow", ("Run", "Devices", "Compare", "Finalize"),
        key="preview_stage", label_visibility="collapsed",
    )
    stage = selected_stage or "Devices"
    if stage in ("Devices", "Compare"):
        group_filter, sweep_filter, status_filter = st.columns([2, 1, 1.4])
        groups = group_filter.multiselect("Groups", GROUPS, placeholder="All groups", key="preview_groups")
        sweeps = sweep_filter.multiselect("Sweep direction", ("Forward", "Reverse"), placeholder="All sweeps", key="preview_sweeps")
        statuses = status_filter.multiselect("Status", ("Valid", "Attention", "Invalid"), placeholder="All statuses", key="preview_status")
        rows = fet_rows(st.session_state["preview_batch"])
        rows = [
            row for row in rows
            if (not groups or row["group"] in groups)
            and (not sweeps or row["sweep"] in sweeps)
            and (not statuses or row["status"] in statuses)
        ]
    if stage == "Compare":
        compare_view(rows)
    elif stage == "Run":
        st.header("Run")
        with st.container(border=True):
            st.write(f"Active batch · {st.session_state['preview_batch']}")
            st.file_uploader("Transfer files", type=["csv", "xls", "xlsx"], accept_multiple_files=True, disabled=True)
            a, b = st.columns(2)
            a.number_input("Channel width (µm)", value=10.0, disabled=True)
            b.number_input("Channel length (µm)", value=5.0, disabled=True)
            st.button("Run analysis", disabled=True, type="primary")
    elif stage == "Finalize":
        st.header("Finalize")
        with st.container(border=True):
            st.write(f"Active batch · {st.session_state['preview_batch']}")
            st.checkbox("Summary CSV", value=True, disabled=True)
            st.checkbox("Metadata JSON", value=True, disabled=True)
            st.button("Export results", disabled=True, type="primary")
    else:
        st.header("Devices")
        if rows:
            devices_view(rows)
        else:
            st.info("No sweeps match the current filters.")

else:
    st.title("Poses")
    stage_bar(("Run", "Poses", "Compare", "Finalize"), "Poses")
    selection = st.segmented_control("Adsorption site", ("Mo top", "S top"), default="Mo top", key="preview_site")
    site = selection or "Mo top"
    viewer, notes = st.columns([2, 1], gap="medium")
    with viewer, st.container(border=True):
        panel_title("CO on MoS₂")
        structure(site)
    with notes:
        with st.container(border=True):
            panel_title("Pose Details")
            st.table([
                {"Property": "Molecule", "Value": "CO"},
                {"Property": "Site", "Value": site},
                {"Property": "Adsorption energy (eV)", "Value": "—"},
                {"Property": "Height (Å)", "Value": "—"},
            ])
        with st.container(border=True):
            panel_title("Binding Curve")
            plot(binding(site), "Distance (Å)", "Energy (eV)", height=195)
