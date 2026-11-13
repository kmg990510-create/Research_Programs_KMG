"""Reader for Keysight B1500 (EasyEXPERT) CSV exports.

Layout: one ``Tag, value, value, ...`` record per line. Header records
(``TestParameter``, ``MetaData``) are ``Tag, key, values...``; one ``DataName``
record names the columns and every ``DataValue`` record is one point. A file
holds one measurement.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from fet_core.config import Config
from fet_core.io.tables import classify_curve, match_columns, resolve_vds, standard_frame, to_float
from fet_core.model import (
    CURVE_UNKNOWN,
    REQUIRED_COLUMNS,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    Measurement,
    WarningRecord,
)
from fet_core.naming import parse_label

NAME = "b1500_csv"
INSTRUMENT = "keysight_b1500"
_CFG = "readers.b1500_csv"


def _records(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [[cell.strip() for cell in row] for row in csv.reader(handle) if row]


def sniff(path: Path, config: Config) -> bool:
    """True when the first lines carry B1500 record tags."""
    tags = set(config.text_list(f"{_CFG}.signature_tags"))
    limit = config.integer(f"{_CFG}.signature_scan_lines")
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
            for _ in range(limit):
                line = handle.readline()
                if not line:
                    break
                if line.split(",", 1)[0].strip() in tags:
                    return True
    except OSError:
        return False
    return False


def _label_from(path: Path, header: dict[str, list[str]], config: Config, field_names: dict[str, str]) -> str:
    match = re.search(config.text(f"{_CFG}.filename_label_pattern"), path.stem)
    if match:
        return match.group("label").strip()
    remarks = header.get(field_names["remarks"], [])
    if remarks and remarks[0]:
        return remarks[0]
    return path.stem


def _conditions(header: dict[str, list[str]], config: Config, field_names: dict[str, str]) -> dict[str, Any]:
    channels = header.get(field_names["channel_voltage_names"], [])
    biases = header.get(field_names["bias_values"], [])
    bias_by_channel = {name: to_float(value) for name, value in zip(channels, biases)}

    locus = (header.get(field_names["sweep_locus"]) or [""])[0]
    recorded = (header.get(field_names["record_time"]) or [""])[0]
    measured_at = None
    if recorded:
        try:
            measured_at = datetime.strptime(recorded, config.text(f"{_CFG}.record_time_format")).isoformat()
        except ValueError:
            measured_at = None
    points = to_float((header.get(field_names["sweep_points"]) or [""])[0])
    return {
        "vd_bias_V": bias_by_channel.get("Vd"),
        "vs_bias_V": bias_by_channel.get("Vs"),
        "sweep_start_V": to_float((header.get(field_names["sweep_start"]) or [""])[0]),
        "sweep_stop_V": to_float((header.get(field_names["sweep_stop"]) or [""])[0]),
        "sweep_points_per_direction": int(points) if points is not None else None,
        "dual_sweep": (locus == config.text(f"{_CFG}.dual_sweep_locus_value")) if locus else None,
        "measured_at": measured_at,
        "measured_at_raw": recorded or None,
    }


def read(path: Path, sha256: str, config: Config) -> tuple[list[Measurement], list[WarningRecord]]:
    """Read one file. Problems are returned as warnings, never raised for bad content."""
    warnings: list[WarningRecord] = []
    run_id = config.text(f"{_CFG}.run_id")
    names_tag = config.text(f"{_CFG}.column_names_tag")
    data_tag = config.text(f"{_CFG}.data_row_tag")
    header_tags = set(config.text_list(f"{_CFG}.header_tags"))
    field_names = config.texts(f"{_CFG}.fields")
    aliases = config.text_lists(f"{_CFG}.columns")

    def warn(code: str, message: str, severity: str = SEVERITY_ERROR, **context: Any) -> None:
        warnings.append(WarningRecord(code, message, path.name, run_id, severity, context))

    header: dict[str, list[str]] = {}
    column_names: list[str] | None = None
    rows: list[list[str]] = []
    for record in _records(path):
        tag, values = record[0], record[1:]
        if tag in header_tags and values:
            header[values[0]] = values[1:]
        elif tag == names_tag:
            column_names = values
        elif tag == data_tag:
            rows.append(values)

    if column_names is None:
        warn("no_column_names", f"No '{names_tag}' record: the data columns cannot be identified.")
        return [], warnings
    if not rows:
        warn("no_data_rows", f"No '{data_tag}' records in the file.")
        return [], warnings

    width = len(column_names)
    ragged = sum(1 for row in rows if len(row) != width)
    if ragged:
        warn(
            "ragged_data_rows",
            f"{ragged} data row(s) do not have {width} values; missing cells are empty, extra cells dropped.",
            severity="warning",
            rows=ragged,
        )
    raw = pd.DataFrame([(row + [""] * width)[:width] for row in rows], columns=column_names)

    column_map = match_columns(column_names, aliases)
    missing = [name for name in REQUIRED_COLUMNS if name not in column_map]
    if missing:
        warn(
            "missing_required_column",
            f"Required column(s) {missing} not found among {column_names}.",
            missing=missing,
            columns=column_names,
        )
        return [], warnings

    frame, non_numeric = standard_frame(raw, column_map)
    if non_numeric:
        warn(
            "non_numeric_cells",
            f"{non_numeric} cell(s) were not numbers and were left empty.",
            severity="warning",
            cells=non_numeric,
        )

    conditions = _conditions(header, config, field_names)
    if conditions["measured_at_raw"] and conditions["measured_at"] is None:
        warn(
            "timestamp_unparsed",
            f"Record time '{conditions['measured_at_raw']}' does not match the expected format.",
            severity=SEVERITY_INFO,
        )
    conditions.update(resolve_vds(frame, conditions["vd_bias_V"], conditions["vs_bias_V"]))

    curve_type = classify_curve(frame, config)
    if curve_type == CURVE_UNKNOWN:
        warn("unknown_curve_type", "Could not tell a transfer from an output curve.", severity="warning")

    name = parse_label(_label_from(path, header, config, field_names), config)
    measurement = Measurement(
        source_file=path,
        source_sha256=sha256,
        instrument=INSTRUMENT,
        run_id=run_id,
        label=name.label,
        group=name.group,
        position=name.position,
        curve_type=curve_type,
        data=frame,
        conditions=conditions,
        metadata={
            "reader": NAME,
            "source_columns": dict(column_map),
            "all_source_columns": list(column_names),
            "remarks": (header.get(field_names["remarks"]) or [None])[0],
        },
    )
    return [measurement], warnings
