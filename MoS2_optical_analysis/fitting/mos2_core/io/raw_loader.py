"""Load raw Raman/PL spectra exported as TXT or simple ASC XY files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from ..core.types import SpectrumRecord

_POINT_RE = re.compile(r"^Y(?P<y>\d+)-X(?P<x>\d+)$", re.IGNORECASE)
_XY_SPLIT_RE = re.compile(r"[\s,;\t]+")


def _infer_modality(header: dict[str, str]) -> str:
    filetype = header.get("FILETYPE", "").upper()
    axis_type = header.get("TYPE", "").upper()
    if "RAMAN" in filetype or "RAMAN" in axis_type:
        return "raman"
    if "PL" in filetype or "PL" in axis_type:
        return "pl"
    return "raman"


def _parse_numeric_xy_lines(lines: list[str], start: int = 0) -> tuple[list[float], list[float]]:
    x_values: list[float] = []
    y_values: list[float] = []
    for raw in lines[start:]:
        line = raw.strip()
        if not line:
            continue
        parts = [part for part in _XY_SPLIT_RE.split(line) if part]
        if len(parts) < 2:
            continue
        try:
            x_values.append(float(parts[0]))
            y_values.append(float(parts[1]))
        except ValueError:
            continue
    return x_values, y_values


def parse_raman_txt(path: str | Path) -> SpectrumRecord:
    """
    Parse one Raman TXT file.

    Format:
    - Header lines in KEY=VALUE format
    - "XYDATA=" marker
    - comma-separated x,y pairs
    """

    file_path = Path(path)
    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()

    header: dict[str, str] = {}
    data_start = -1
    for idx, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        if line.upper() == "XYDATA=":
            data_start = idx + 1
            break
        if "=" in line:
            key, value = line.split("=", 1)
            header[key.strip()] = value.strip()

    if data_start < 0:
        x_values, y_values = _parse_numeric_xy_lines(lines)
        if not x_values:
            raise ValueError(f"XYDATA marker not found and no numeric XY rows parsed: {file_path}")
        if file_path.suffix.lower() == ".asc":
            header["FILETYPE"] = header.get("FILETYPE", "PL_ASC")
            header["TYPE"] = header.get("TYPE", "PL")
            header["X_UNIT"] = header.get("X_UNIT", "nm")
    else:
        x_values, y_values = _parse_numeric_xy_lines(lines, start=data_start)

    if not x_values or len(x_values) != len(y_values):
        raise ValueError(f"Failed to parse XY data: {file_path}")

    expected_len = header.get("LEN")
    if expected_len is not None:
        try:
            expected = int(float(expected_len))
            if expected != len(x_values):
                header["LEN_MISMATCH"] = f"expected={expected};actual={len(x_values)}"
        except ValueError:
            pass

    stem = file_path.stem
    parent = file_path.parent.name
    point_match = _POINT_RE.match(stem)

    metadata: dict[str, object] = {
        "source_file": str(file_path),
        "dataset": parent,
        "header": header,
        "map_id": parent,
        "source_extension": file_path.suffix.lower(),
    }
    if point_match:
        metadata["map_y"] = int(point_match.group("y"))
        metadata["map_x"] = int(point_match.group("x"))

    return SpectrumRecord(
        spectrum_id=f"{parent}:{stem}",
        x=x_values,
        y=y_values,
        modality=_infer_modality(header),
        metadata=metadata,
    )


def load_raman_txt_directory(
    directory: str | Path,
    pattern: str = "*.txt",
) -> list[SpectrumRecord]:
    """Load all TXT spectra in a directory."""

    root = Path(directory)
    files = sorted(root.glob(pattern))
    return [parse_raman_txt(path) for path in files]


def load_raman_txt_paths(paths: Iterable[str | Path]) -> list[SpectrumRecord]:
    """Load spectra from an explicit list of file paths."""

    return [parse_raman_txt(p) for p in paths]
