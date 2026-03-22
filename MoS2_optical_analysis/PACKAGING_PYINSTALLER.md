# PyInstaller Packaging Notes

## Overview

This project is packaged as a mixed Python application (pipeline + Streamlit + PySide6), not as a pure PySide6 app.

The spec file is:

- `mos2_optical_analysis.spec`

It builds four executables so frozen subprocess calls continue to work:

- `mos2-analysis` (Streamlit launcher)
- `mos2-run-raman` (Raman raw pipeline runner)
- `mos2-run-pl` (PL raw pipeline runner)
- `mos2-desktop-editor` (PySide6 manual editor)

## Build Command

From repository root:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --distpath dist --workpath dist/build mos2_optical_analysis.spec
```

Notes:

- `dist/mos2-analysis` is the distributable folder.
- `dist/build` is temporary PyInstaller work output.
- Close running `mos2-*.exe` before rebuilding (Windows file lock).

## Included in Bundle

- `gui/**` Python sources (needed by Streamlit multipage discovery)
- Raman/PL config YAML files:
  - `fitting/mos2_raman/config/*.yaml`
  - `fitting/mos2_pl/config/*.yaml`
- Streamlit/visualization package metadata needed by runtime imports/version checks

## Intentionally Excluded

- Runtime outputs such as `data/results/**` and `data/bin/results/**`
- User-generated manual refit history (`manual_refits.jsonl`)
- Legacy code under `legacy/**`

These are expected to be generated/managed externally at runtime.

## Runtime Output Location (Packaged App)

- In frozen execution, runtime-generated outputs are written outside the executable binary under:
  - `dist/mos2-analysis/data/results/...`
- The executable itself is not modified; outputs are regular external files.

## About `dist_progressfix` / `build_progressfix`

- These were temporary fallback outputs used when the normal `dist/mos2-analysis` folder was locked by a running process.
- They are not required for normal packaging or distribution.
- Standardize on:
  - `dist/mos2-analysis` (deliverable)
  - `dist/build` (temporary build work)

## Distribution Checklist (Minimum)

Distribute the whole `dist/mos2-analysis` folder, including:

- `mos2-analysis.exe`
- `mos2-run-raman.exe`
- `mos2-run-pl.exe`
- `mos2-desktop-editor.exe`
- `_internal/` (required runtime libraries/assets)
- `PACKAGING_DIST_README.md` (minimal end-user usage note)

## Packaging Compatibility Adjustments

- `gui/pages/1_Run_Analysis.py` now detects frozen mode and launches:
  - `mos2-run-raman(.exe)` or `mos2-run-pl(.exe)`
- `gui/pages/2_All_Spectra_Viewer.py` now detects frozen mode and launches:
  - `mos2-desktop-editor(.exe)`

Non-frozen behavior still uses `sys.executable -m ...` exactly as before.
