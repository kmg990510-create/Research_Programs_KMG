"""Reader for Keithley 4200A (Clarius) ``.xls`` workbooks.

Layout: one data sheet per run (header row, then one point per row), an empty
``Calc`` sheet, and a ``Settings`` sheet with one block per run. A block opens
with ``=====`` / run name / ``=====``, lists ``key, value`` rows, and holds a
per-terminal table that starts at the ``Device Terminal`` row.

Parsing works on plain rows (``parse_workbook``) so it can be tested without
an ``.xls`` file; ``read_sheets`` is the only place that touches ``xlrd``.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from fet_core.config import Config
from fet_core.io.tables import classify_curve, match_columns, resolve_vds, standard_frame, to_float
from fet_core.model import (
    CURVE_UNKNOWN,
    REQUIRED_COLUMNS,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    Measurement,
    WarningRecord,
)
from fet_core.naming import parse_label

NAME = "clarius_xls"
INSTRUMENT = "keithley_4200a_clarius"
_CFG = "readers.clarius_xls"

Rows = Sequence[Sequence[Any]]


def read_sheets(path: Path) -> dict[str, list[list[Any]]]:
    """Every sheet as a list of rows, in workbook order."""
    import xlrd

    workbook = xlrd.open_workbook(str(path))
    return {sheet.name: [sheet.row_values(r) for r in range(sheet.nrows)] for sheet in workbook.sheets()}


def _cell_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _is_data_sheet(rows: Rows, aliases: Mapping[str, Sequence[str]]) -> bool:
    if not rows:
        return False
    matched = match_columns([_cell_text(cell) for cell in rows[0]], aliases)
    return all(name in matched for name in REQUIRED_COLUMNS)


def sniff(path: Path, config: Config) -> bool:
    """True when the workbook has at least one sheet with gate-voltage and drain-current columns."""
    aliases = config.text_lists(f"{_CFG}.columns")
    try:
        sheets = read_sheets(path)
    except Exception:  # not a readable .xls workbook
        return False
    return any(_is_data_sheet(rows, aliases) for rows in sheets.values())


def parse_settings(rows: Rows, config: Config) -> dict[str, dict[str, Any]]:
    """Settings blocks by run name: scalar ``fields`` and a per-terminal ``terminals`` table."""
    prefix = config.text(f"{_CFG}.settings.block_separator_prefix")
    terminal_header = config.text(f"{_CFG}.settings.terminal_header")

    def is_separator(index: int) -> bool:
        return 0 <= index < len(rows) and bool(rows[index]) and _cell_text(rows[index][0]).startswith(prefix)

    starts = [i for i in range(len(rows) - 2) if is_separator(i) and is_separator(i + 2)]
    blocks: dict[str, dict[str, Any]] = {}
    for position, start in enumerate(starts):
        name = _cell_text(rows[start + 1][0]) if rows[start + 1] else ""
        end = starts[position + 1] if position + 1 < len(starts) else len(rows)
        fields: dict[str, str] = {}
        terminals: dict[str, dict[str, str]] = {}
        terminal_names: list[str] = []
        for row in rows[start + 3 : end]:
            if not row or not _cell_text(row[0]):
                continue
            key = _cell_text(row[0])
            values = [_cell_text(cell) for cell in row[1:]]
            if key == terminal_header:
                terminal_names = values
                terminals = {terminal: {} for terminal in terminal_names if terminal}
            elif terminal_names:
                for terminal, value in zip(terminal_names, values):
                    if terminal:
                        terminals[terminal][key] = value
            else:
                fields[key] = values[0] if values else ""
        if name:
            blocks[name] = {"fields": fields, "terminals": terminals}
    return blocks


def _conditions(block: dict[str, Any] | None, config: Config) -> dict[str, Any]:
    names = config.texts(f"{_CFG}.settings.terminals")
    keys = config.texts(f"{_CFG}.settings.fields")
    enabled = config.text(f"{_CFG}.settings.dual_sweep_enabled_value")
    time_format = config.text(f"{_CFG}.settings.measured_at_format")
    empty = {
        "vd_bias_V": None,
        "vs_bias_V": None,
        "sweep_start_V": None,
        "sweep_stop_V": None,
        "sweep_step_V": None,
        "dual_sweep": None,
        "measured_at": None,
        "measured_at_raw": None,
    }
    if block is None:
        return empty
    terminals = block["terminals"]
    gate = terminals.get(names["gate"], {})
    drain = terminals.get(names["drain"], {})
    source = terminals.get(names["source"], {})
    dual = gate.get(keys["dual_sweep"])
    recorded = block["fields"].get(keys["measured_at"], "")
    measured_at = None
    if recorded:
        try:
            measured_at = datetime.strptime(recorded, time_format).isoformat()
        except ValueError:
            measured_at = None
    return {
        "vd_bias_V": to_float(drain.get(keys["bias"])),
        "vs_bias_V": to_float(source.get(keys["bias"])),
        "sweep_start_V": to_float(gate.get(keys["bias"])),
        "sweep_stop_V": to_float(gate.get(keys["stop"])),
        "sweep_step_V": to_float(gate.get(keys["step"])),
        "dual_sweep": (dual == enabled) if dual else None,
        "measured_at": measured_at,
        "measured_at_raw": recorded or None,
    }


def parse_workbook(
    sheets: Mapping[str, Rows],
    source_file: Path,
    sha256: str,
    config: Config,
) -> tuple[list[Measurement], list[WarningRecord]]:
    """Turn workbook rows into measurements. One data sheet is one run."""
    aliases = config.text_lists(f"{_CFG}.columns")
    settings_names = {name.casefold() for name in config.text_list(f"{_CFG}.settings_sheet_names")}
    unnamed_run = re.compile(config.text(f"{_CFG}.unnamed_run_pattern"))
    warnings: list[WarningRecord] = []
    measurements: list[Measurement] = []

    def warn(run_id: str | None, code: str, message: str, severity: str, **context: Any) -> None:
        warnings.append(WarningRecord(code, message, source_file.name, run_id, severity, context))

    settings_rows = next((rows for name, rows in sheets.items() if name.strip().casefold() in settings_names), None)
    blocks = parse_settings(settings_rows, config) if settings_rows else {}
    if settings_rows is None:
        warn(None, "settings_sheet_missing", "No Settings sheet: sweep conditions come from the data only.", SEVERITY_WARNING)

    for sheet_name, rows in sheets.items():
        if sheet_name.strip().casefold() in settings_names or not rows:
            continue
        header = [_cell_text(cell) for cell in rows[0]]
        column_map = match_columns(header, aliases)
        missing = [name for name in REQUIRED_COLUMNS if name not in column_map]
        if missing:
            warn(
                sheet_name,
                "missing_required_column",
                f"Sheet '{sheet_name}' skipped: column(s) {missing} not found among {header}.",
                SEVERITY_ERROR,
                missing=missing,
                columns=header,
            )
            continue
        if len(rows) < 2:
            warn(sheet_name, "no_data_rows", f"Sheet '{sheet_name}' has a header but no points.", SEVERITY_ERROR)
            continue

        width = len(header)
        raw = pd.DataFrame([(list(row) + [""] * width)[:width] for row in rows[1:]], columns=header)
        frame, non_numeric = standard_frame(raw, column_map)
        if non_numeric:
            warn(
                sheet_name,
                "non_numeric_cells",
                f"{non_numeric} cell(s) were not numbers and were left empty.",
                SEVERITY_WARNING,
                cells=non_numeric,
            )

        block = blocks.get(sheet_name.strip())
        if settings_rows is not None and block is None:
            warn(
                sheet_name,
                "settings_block_missing",
                f"Settings sheet has no block for '{sheet_name}': sweep conditions come from the data only.",
                SEVERITY_WARNING,
            )
        conditions = _conditions(block, config)
        if conditions["measured_at_raw"] and conditions["measured_at"] is None:
            warn(
                sheet_name,
                "timestamp_unparsed",
                f"Execution time '{conditions['measured_at_raw']}' does not match the expected format.",
                SEVERITY_INFO,
            )
        conditions.update(resolve_vds(frame, conditions["vd_bias_V"], conditions["vs_bias_V"]))

        curve_type = classify_curve(frame, config)
        if curve_type == CURVE_UNKNOWN:
            warn(sheet_name, "unknown_curve_type", "Could not tell a transfer from an output curve.", SEVERITY_WARNING)

        # A sheet the operator did not rename ("Run2711") says nothing about the device.
        named = not unnamed_run.fullmatch(sheet_name.strip())
        name = parse_label(sheet_name if named else source_file.stem, config)
        measurements.append(
            Measurement(
                source_file=source_file,
                source_sha256=sha256,
                instrument=INSTRUMENT,
                run_id=sheet_name.strip(),
                label=name.label,
                group=name.group,
                position=name.position,
                curve_type=curve_type,
                data=frame,
                conditions=conditions,
                metadata={
                    "reader": NAME,
                    "source_columns": dict(column_map),
                    "all_source_columns": header,
                    "label_from": "sheet_name" if named else "file_name",
                    "test_name": (block or {}).get("fields", {}).get("Test Name"),
                },
            )
        )
    return measurements, warnings


def read(path: Path, sha256: str, config: Config) -> tuple[list[Measurement], list[WarningRecord]]:
    return parse_workbook(read_sheets(path), path, sha256, config)
