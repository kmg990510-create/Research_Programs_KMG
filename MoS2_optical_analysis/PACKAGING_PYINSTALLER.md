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
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm mos2_optical_analysis.spec
```

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

## Packaging Compatibility Adjustments

- `gui/pages/1_Run_Analysis.py` now detects frozen mode and launches:
  - `mos2-run-raman(.exe)` or `mos2-run-pl(.exe)`
- `gui/pages/2_All_Spectra_Viewer.py` now detects frozen mode and launches:
  - `mos2-desktop-editor(.exe)`

Non-frozen behavior still uses `sys.executable -m ...` exactly as before.
