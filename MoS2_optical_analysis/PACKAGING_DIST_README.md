# MoS2 Optical Analysis (Packaged App)

## What to Run

- Main UI: `mos2-analysis.exe`
- Raman CLI runner: `mos2-run-raman.exe`
- PL CLI runner: `mos2-run-pl.exe`
- Desktop manual editor worker: `mos2-desktop-editor.exe`

## Quick Start (UI)

1. Run `mos2-analysis.exe`.
2. Open the URL shown in terminal (`http://localhost:8501` by default).
3. If `8501` is busy, use the printed URL (for example `8502`).

## Optional Fixed Port

- `mos2-analysis.exe --server.headless true --server.port 8512`
- Then open `http://localhost:8512`.

## CLI Examples

- Raman single:
  - `mos2-run-raman.exe --raw-dir data\raw\raman\... --run-id my_raman`
- Raman batch:
  - `mos2-run-raman.exe --raw-dir data\raw\raman\... --batch-subdirs`
- PL single:
  - `mos2-run-pl.exe --raw-dir data\raw\pl\... --run-id my_pl`
- PL batch:
  - `mos2-run-pl.exe --raw-dir data\raw\pl\... --batch-subdirs`

## Output Location

- Results are written under `data\results\...` next to the executable folder.
- `results` data is external runtime output and is not embedded inside the executable.
