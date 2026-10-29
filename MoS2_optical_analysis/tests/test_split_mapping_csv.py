from __future__ import annotations

from pathlib import Path

import pytest

from fitting.mos2_core.io import parse_raman_txt
from fitting.mos2_raman.split_mapping_csv import split_mapping_csv


def _write_mapping_csv(path: Path, truncate_last: bool = False) -> None:
    axis = ["380.0", "390.0", "400.0"]
    lines = [
        "FILETYPE=RAMAN SPECTRUM (MAPPING)",
        "TYPE=RamanShift",
        "LASER=532nm",
        "CCD=Artemis",
        "IT=1000ms",
        "DATETIME=2026-10-22 13:55:46",
        "XAREA=Min:-0.3, Max:0.3, Step:0.3, Count:3",
        "YAREA=Min:-0.15, Max:0.15, Step:0.3, Count:2",
        "AXISDATA=",
        "X,Y,Z,XINDEX,YINDEX,ZINDEX," + ",".join(axis) + ",",
    ]
    rows = [(xi, yi) for yi in range(2) for xi in range(3)]
    for xi, yi in rows:
        values = [str(100 * yi + 10 * xi + k) for k in range(3)]
        lines.append(f"{-0.3 + 0.3 * xi},{-0.15 + 0.3 * yi},0,{xi},{yi},0," + ",".join(values) + ",")
    if truncate_last:
        lines[-1] = lines[-1].rsplit(",", 3)[0] + ","
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_split_mapping_csv_writes_loader_compatible_txt(tmp_path: Path) -> None:
    csv_path = tmp_path / "sample_spectrum.CSV"
    _write_mapping_csv(csv_path)

    result = split_mapping_csv(csv_path)

    assert result.out_dir == tmp_path / "sample_spectrum"
    assert (result.written, result.truncated_rows, result.missing) == (6, 0, [])
    record = parse_raman_txt(result.out_dir / "Y02-X03.txt")
    assert record.modality == "raman"
    assert (record.metadata["map_y"], record.metadata["map_x"]) == (2, 3)
    assert record.x == [380.0, 390.0, 400.0]
    assert record.y == [120.0, 121.0, 122.0]
    assert record.metadata["header"]["LASER"] == "532"
    assert "LEN_MISMATCH" not in record.metadata["header"]


def test_split_mapping_csv_skips_truncated_rows_and_reports_missing(tmp_path: Path) -> None:
    csv_path = tmp_path / "cut.CSV"
    _write_mapping_csv(csv_path, truncate_last=True)

    result = split_mapping_csv(csv_path)

    assert (result.written, result.truncated_rows) == (5, 1)
    assert result.missing == [(2, 3)]
    assert not (result.out_dir / "Y02-X03.txt").exists()


def test_split_mapping_csv_refuses_existing_output_without_overwrite(tmp_path: Path) -> None:
    csv_path = tmp_path / "again.CSV"
    _write_mapping_csv(csv_path)
    split_mapping_csv(csv_path)

    with pytest.raises(FileExistsError):
        split_mapping_csv(csv_path)
    assert split_mapping_csv(csv_path, overwrite=True).written == 6
