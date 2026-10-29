"""Split a Raman mapping CSV export into per-point TXT spectra.

Some instruments (e.g. CCD=Artemis exports, `FILETYPE=RAMAN SPECTRUM (MAPPING)`)
save a whole map as one CSV:

- KEY=VALUE header lines (`XAREA=... Count:N`, `YAREA=... Count:M`, ...)
- column row `X,Y,Z,XINDEX,YINDEX,ZINDEX,<raman shift 1>,<raman shift 2>,...`
- one row per map point: stage position, 0-based indices, then intensities

The pipeline loader (`fitting.mos2_core.io.raw_loader`) expects one TXT file per
point named `Y<n>-X<n>.txt`, so this tool writes
`<csv parent>/<csv stem>/Y###-X###.txt` (1-based, from YINDEX/XINDEX) in the
KEY=VALUE + `XYDATA=` format. Truncated rows (incomplete scans) are skipped and
reported; missing grid points are listed in the summary.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path


COLUMN_ROW_PREFIX = "X,Y,Z,XINDEX,YINDEX,ZINDEX,"


@dataclass(slots=True)
class SplitResult:
    csv_path: Path
    out_dir: Path
    x_count: int
    y_count: int
    written: int = 0
    truncated_rows: int = 0
    missing: list[tuple[int, int]] = field(default_factory=list)

    @property
    def expected(self) -> int:
        return self.x_count * self.y_count


def _area_count(value: str) -> int:
    # "Min:-20.43, Max:20.43, Step:0.3, Count:137"
    return int(value.split("Count:")[1].split(",")[0].strip())


def split_mapping_csv(
    csv_path: str | Path,
    out_dir: str | Path | None = None,
    overwrite: bool = False,
) -> SplitResult:
    """Write one TXT per map point from a mapping CSV and return a summary."""

    csv_path = Path(csv_path)
    target = Path(out_dir) if out_dir is not None else csv_path.with_suffix("")
    if target.exists() and any(target.glob("*.txt")) and not overwrite:
        raise FileExistsError(f"output folder already has TXT files (use --overwrite): {target}")

    header: dict[str, str] = {}
    with csv_path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if line.startswith(COLUMN_ROW_PREFIX):
                axis = [v.strip() for v in line.split(",")[6:] if v.strip()]
                break
            if "=" in line:
                key, value = line.split("=", 1)
                header[key.strip()] = value.strip()
        else:
            raise ValueError(f"column row '{COLUMN_ROW_PREFIX}...' not found: {csv_path}")

        result = SplitResult(
            csv_path=csv_path,
            out_dir=target,
            x_count=_area_count(header["XAREA"]),
            y_count=_area_count(header["YAREA"]),
        )
        pad = max(2, len(str(max(result.x_count, result.y_count))))
        laser = header.get("LASER", "").lower().replace("nm", "").strip()
        target.mkdir(parents=True, exist_ok=True)

        seen: set[tuple[int, int]] = set()
        for line in fh:
            parts = line.rstrip("\r\n").split(",")
            if len(parts) < 6:
                continue
            values = [v.strip() for v in parts[6:] if v.strip()]
            if len(values) != len(axis):
                result.truncated_rows += 1
                continue
            xi, yi = int(parts[3]) + 1, int(parts[4]) + 1
            seen.add((yi, xi))
            lines = [
                "FILETYPE=RAMAN SPECTRUM",
                f"DATETIME={header.get('DATETIME', '')}",
                f"CCD={header.get('CCD', '')}",
                f"LASER={laser}",
                f"IT={header.get('IT', '')}",
                "TYPE=RamanShift",
                "XUNITS=1/cm",
                f"XPOSITION={parts[0]}",
                f"YPOSITION={parts[1]}",
                f"SOURCE_CSV={csv_path.name}",
                f"LEN={len(axis)}",
                "XYDATA=",
            ]
            lines.extend(f"{x},{y}" for x, y in zip(axis, values))
            name = f"Y{yi:0{pad}d}-X{xi:0{pad}d}.txt"
            (target / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
            result.written += 1

    result.missing = [
        (y, x)
        for y in range(1, result.y_count + 1)
        for x in range(1, result.x_count + 1)
        if (y, x) not in seen
    ]
    return result


def _format_summary(result: SplitResult) -> str:
    lines = [
        f"{result.csv_path.name}",
        f"  -> {result.out_dir}",
        f"  grid {result.x_count}(X) x {result.y_count}(Y) = {result.expected}, "
        f"written {result.written}, truncated rows {result.truncated_rows}",
    ]
    if result.missing:
        first, last = result.missing[0], result.missing[-1]
        lines.append(
            f"  missing {len(result.missing)} points: "
            f"first Y{first[0]}-X{first[1]}, last Y{last[0]}-X{last[1]}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csv", nargs="+", type=Path, help="mapping CSV file(s)")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="output folder (single CSV only; default: <csv parent>/<csv stem>)",
    )
    parser.add_argument("--overwrite", action="store_true", help="allow writing into a folder with TXT files")
    args = parser.parse_args(argv)

    if args.out_dir is not None and len(args.csv) > 1:
        parser.error("--out-dir can only be used with a single CSV")
    for csv_path in args.csv:
        print(_format_summary(split_mapping_csv(csv_path, out_dir=args.out_dir, overwrite=args.overwrite)))


if __name__ == "__main__":
    main()
