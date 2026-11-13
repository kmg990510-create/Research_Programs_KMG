"""Shared fixtures: config, a synthetic device, and vendor-format writers.

Tests never read files under ``data/raw``. Vendor files are written on the fly
from synthetic curves.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from fet_core.config import Config, load_config
from fet_core.model import DeviceGeometry
from fet_core.synth import SyntheticDevice, transfer_curve


@pytest.fixture
def config() -> Config:
    return load_config()


@pytest.fixture
def device(config: Config) -> SyntheticDevice:
    return SyntheticDevice(
        geometry=DeviceGeometry.from_config(config),
        vth_V=5.0,
        ss_mV_per_dec=800.0,
        mobility_cm2_per_Vs=20.0,
        vds_V=1.0,
    )


@pytest.fixture
def curve(device: SyntheticDevice) -> pd.DataFrame:
    return transfer_curve(device, -40.0, 60.0, 0.5, dual=True)


def write_b1500_csv(
    path: Path,
    frame: pd.DataFrame,
    *,
    gate_column: str = "Vbg",
    gate_current_column: str = "Ibg",
    locus: str = "Double",
    record_time: str = "09/16/2026 00:18:08",
    remarks: str = "",
    extra_columns: bool = True,
) -> Path:
    """Write ``frame`` (standard columns) as a B1500 EasyEXPERT CSV export."""
    start, stop = float(frame["Vg"].iloc[0]), float(frame["Vg"].max())
    count = (len(frame) + 1) // 2 if locus == "Double" else len(frame)
    lines = [
        "",
        "SetupTitle, Transfer BG_NFET",
        "PrimitiveTest, Multi Channel I/V Sweep",
        "TestParameter, Channel.IName, Id, Ibg, Is",
        f"TestParameter, Channel.VName, Vd, {gate_column}, Vs",
        "TestParameter, Channel.Func, CONST, VAR1, CONST",
        f"TestParameter, Measurement.Primary.Start, {start:g}",
        f"TestParameter, Measurement.Primary.Stop, {stop:g}",
        f"TestParameter, Measurement.Primary.Locus, {locus}",
        f"TestParameter, Measurement.Primary.Count, {count}",
        f"TestParameter, Measurement.Bias.Source, {float(frame['Vd'].iloc[0]):g}, {start:g}, 0",
        f"MetaData, TestRecord.RecordTime, {record_time}",
        f"MetaData, TestRecord.Remarks, {remarks}",
        "AnalysisSetup, Analysis.Setup.Vector.Graph.YAxis.Name, Id, absIbg",
    ]
    names = [gate_column, "Vd", "Id", gate_current_column]
    if extra_columns:
        names += ["absId", "absIbg"]
    lines.append("DataName, " + ", ".join(names))
    for row in frame.itertuples(index=False):
        values = [row.Vg, row.Vd, row.Id, row.Ig]
        if extra_columns:
            values += [abs(row.Id), abs(row.Ig)]
        lines.append("DataValue, " + ", ".join(repr(float(v)) for v in values))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return path


def clarius_data_rows(frame: pd.DataFrame, with_source: bool = False) -> list[list]:
    """A Clarius data sheet: header row, then one point per row."""
    header = ["DrainI", "DrainV"] + (["SourceV"] if with_source else []) + ["GateI", "GateV"]
    rows: list[list] = [header]
    for row in frame.itertuples(index=False):
        rows.append([row.Id, row.Vd] + ([0.0] if with_source else []) + [row.Ig, row.Vg])
    return rows


def clarius_settings_rows(
    run_names: list[str], *, vd: float = 1.0, start: float = -40.0, stop: float = 60.0
) -> list[list]:
    """A Clarius Settings sheet with one block per run."""
    rows: list[list] = []
    for name in run_names:
        rows += [
            ["======================", "", "", ""],
            [name, "", "", ""],
            ["======================", "", "", ""],
            ["", "", "", ""],
            ["Test Name", "vgs-id#1@1", "", ""],
            ["Last Executed", "08/13/2026 21:55:13", "", ""],
            ["", "", "", ""],
            ["Device Terminal", "Drain", "Source", "Gate"],
            ["Name", "DrainV", "SourceV", "GateV"],
            ["Operation Mode", "Voltage Bias", "Voltage Bias", "Voltage Linear Sweep"],
            ["Start/Bias", str(vd), "0", str(start)],
            ["Stop", "N/A", "N/A", str(stop)],
            ["Step", "N/A", "N/A", "1"],
            ["Dual Sweep", "N/A", "N/A", "Enabled"],
            ["Compensation", "NA", "", ""],
        ]
    return rows
