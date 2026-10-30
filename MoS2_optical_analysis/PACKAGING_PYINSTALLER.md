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
Copy-Item -Path PACKAGING_DIST_README.md -Destination dist/mos2-analysis/PACKAGING_DIST_README.md -Force
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
- User-generated manual overrides (`data/results/{modality}/manual_refits/*_manual_overrides.json`)
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
- If old top-level `build/`, `build_progressfix/`, or `dist_progressfix/` folders exist from earlier runs, treat them as legacy leftovers and do not use them for release artifacts.

## Distribution Checklist (Minimum)

Distribute the whole `dist/mos2-analysis` folder, including:

- `mos2-analysis.exe`
- `mos2-run-raman.exe`
- `mos2-run-pl.exe`
- `mos2-desktop-editor.exe`
- `_internal/` (required runtime libraries/assets)
- `PACKAGING_DIST_README.md` (minimal end-user usage note)
- `data/raw/raman/`, `data/raw/pl/` (empty input folders, created by the spec)
- `config.yaml` (user-editable scientific settings, copied next to the exe by the spec)

## Packaging Compatibility Adjustments

- `gui/pages/1_Run_Analysis.py` now detects frozen mode and launches:
  - `mos2-run-raman(.exe)` or `mos2-run-pl(.exe)`
- `gui/pages/3_All_Spectra_Viewer.py` now detects frozen mode and launches:
  - `mos2-desktop-editor(.exe)`

Non-frozen behavior still uses `sys.executable -m ...` exactly as before.

## Frozen Path Rules (2026-10-29)

- User data (`data/raw`, `data/results`, `data/bin`) resolves from the exe folder:
  `runtime_project_root()`.
- Bundled config YAML resolves from the PyInstaller bundle dir (`sys._MEIPASS`, i.e. `_internal`):
  `runtime_resource_root()` / `raman_config_dir()` in `fitting/mos2_core/core/runtime_paths.py`.
- GUI graph style, report loader graph config, `SingleSpectrumRefitAPI`, and the desktop editor all use
  `raman_config_dir()`. Before this, All Spectra manual refit looked for
  `<exe folder>/fitting/mos2_raman/config` and failed in the packaged app.
- `data/raw/raman` and `data/raw/pl` are shipped empty: the spec creates them after `COLLECT` with a
  `_PUT_SAMPLE_FOLDERS_HERE.md` placeholder (keeps them through zip/copy; `.md` is not a spectrum pattern).
- `config.yaml` resolves from the exe folder first (`runtime_paths.user_config_path()`), then the bundled copy
  in `_internal`. The spec bundles it as data and copies it next to the exe after `COLLECT`.

## Multiprocessing Workers in Frozen Mode

- `packaging/entry_run_raman.py` and `packaging/entry_run_pl.py` call `multiprocessing.freeze_support()`
  before `main()`.
- Needed for `--workers > 1`: `ProcessPoolExecutor` children re-launch the same exe with
  `--multiprocessing-fork`; without `freeze_support()` they would run the CLI `main()` instead of the
  worker loop and the pool would break.
- If the pool still breaks (`BrokenExecutor`), `raman_lmfit` now finishes the remaining spectra on the
  sequential path and logs `[fit] multiprocessing disabled; fallback to sequential (...)`.
  Previously each pending spectrum was recorded as `invalid` (`fit_worker_exception`).
- After a rebuild, verify with `mos2-run-raman.exe --raw-dir <folder> --run-id mp_check --workers 4`
  and confirm the log does not contain `fallback to sequential`.
