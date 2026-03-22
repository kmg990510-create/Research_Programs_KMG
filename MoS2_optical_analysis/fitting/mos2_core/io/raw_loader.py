"""Load raw Raman TXT spectra exported by XperRAM-like software."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from ..core.types import SpectrumRecord

_POINT_RE = re.compile(r"^Y(?P<y>\d+)-X(?P<x>\d+)$", re.IGNORECASE)


def _infer_modality(header: dict[str, str]) -> str:
    filetype = header.get("FILETYPE", "").upper()
    axis_type = header.get("TYPE", "").upper()
    if "RAMAN" in filetype or "RAMAN" in axis_type:
        return "raman"
    if "PL" in filetype or "PL" in axis_type:
        return "pl"
    return "raman"


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
        raise ValueError(f"XYDATA marker not found: {file_path}")

    x_values: list[float] = []
    y_values: list[float] = []
    for raw in lines[data_start:]:
        line = raw.strip()
        if not line:
            continue
        if "," not in line:
            continue
        left, right = line.split(",", 1)
        try:
            x_values.append(float(left.strip()))
            y_values.append(float(right.strip()))
        except ValueError:
            continue

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

