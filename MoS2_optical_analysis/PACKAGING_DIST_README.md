# MoS2 Optical Analysis (Packaged App)

## What to Run

- Main UI: `mos2-analysis.exe`
- Raman CLI runner: `mos2-run-raman.exe`
- PL CLI runner: `mos2-run-pl.exe`
- Desktop manual editor worker: `mos2-desktop-editor.exe`

## First-Time Setup: Data Folders

The app reads spectra from `data\raw\...` next to the `.exe` files. These folders are
not shipped, so create them once before the first run:

```
mos2-analysis\
  mos2-analysis.exe
  mos2-run-raman.exe
  ...
  data\
    raw\
      raman\      <- put Raman sample folders here
      pl\         <- put PL sample folders here
```

PowerShell (run inside the `mos2-analysis` folder):

```powershell
New-Item -ItemType Directory -Force data\raw\raman, data\raw\pl
```

- Put one sample per folder, e.g. `data\raw\raman\SampleA\Y1-X1.txt, Y1-X2.txt, ...`.
- Raman files default to `*.txt`; PL files default to `*.asc`.
- For batch runs, group several sample folders under one parent folder
  (e.g. `data\raw\raman\Batch_1\SampleA`, `data\raw\raman\Batch_1\SampleB`).
- `data\results\...` (reports) and `data\bin\...` (Result Bin) are created automatically.
- A folder outside `data\raw` can also be used via the custom folder input in Run Analysis.

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
- Parallel fitting (spectrum-level, any of the above):
  - add `--workers 4` (or set `fit_workers` in Run Analysis); `1` = sequential

## Output Location

- Results are written under `data\results\...` next to the executable folder.
- `results` data is external runtime output and is not embedded inside the executable.
