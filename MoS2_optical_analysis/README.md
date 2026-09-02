# MoS2 Fit Workspace

Current workspace is organized into `fitting`, `gui`, and `data`.

## Structure

- `fitting/mos2_core`: shared pipeline modules
- `fitting/mos2_raman`: Raman entrypoints and config
- `fitting/mos2_pl`: PL entrypoints and config
- `gui`: Streamlit UI
- `data/raw`: input data root
- `data/bin/results`: soft-delete staging area (trash for result files)
- `data/results`: output reports root

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Run Pipelines

```powershell
# Raman dummy
.\.venv\Scripts\python.exe -m fitting.mos2_raman.run_dummy_pipeline

# Raman raw (single folder)
.\.venv\Scripts\python.exe -m fitting.mos2_raman.run_raw_pipeline --raw-dir data/raw/raman/... --run-id raman_run

# Raman raw (batch: immediate subfolders)
.\.venv\Scripts\python.exe -m fitting.mos2_raman.run_raw_pipeline --raw-dir data/raw/raman/... --batch-subdirs

# Raman raw with spectrum-level multiprocessing
.\.venv\Scripts\python.exe -m fitting.mos2_raman.run_raw_pipeline --raw-dir data/raw/raman/... --run-id raman_run_mp --workers 4

# PL dummy
.\.venv\Scripts\python.exe -m fitting.mos2_pl.run_dummy_pipeline

# PL raw (single folder)
.\.venv\Scripts\python.exe -m fitting.mos2_pl.run_raw_pipeline --raw-dir data/raw/pl/... --run-id pl_run

# PL raw (batch: immediate subfolders)
.\.venv\Scripts\python.exe -m fitting.mos2_pl.run_raw_pipeline --raw-dir data/raw/pl/... --batch-subdirs
```

Note:
- In single mode, if `--raw-dir` has no direct files matching `--pattern` but has matching immediate subfolders, `run_raw_pipeline` auto-switches to batch-subdirs mode.
- `--workers` controls spectrum-level fit multiprocessing (`1` = sequential). In restricted environments, pipeline auto-falls back to sequential and logs the reason.
- PL raw runs default to `*.asc`. Headerless ASC files containing numeric `wavelength_nm,intensity` rows are supported.
- PL wavelengths that look like nm are converted before fitting with `eV = 1239.8419843320026 / nm`; PL fit config values are therefore in eV.
- PL intensity density correction is available as `pl.intensity_density_correction.enabled` and defaults to `false`.
- PL fitting uses PL-specific candidate models by default: `pl_single_pvoigt`, `pl_a_doublet_pvoigt`, and `pl_5_component_pvoigt`.
- PL component seeds/bounds live in `fitting/mos2_pl/config/pl.yaml` under `fit.components`; the default components are `I1`, `I2`, `A_minus`, `A0`, and `B`.
- PL report rows include component positions/FWHM/heights/areas/fractions plus derived comparison metrics such as `a_minus_a0_area_ratio`, `a0_fraction_of_a_total`, `b_to_a_total_area_ratio`, and `defect_to_a_total_area_ratio`.

## Experimental Fitting Guardrail

TASK-021 adds a non-production comparison runner for the proposed `scipy.optimize.least_squares`
Raman hot path. It does not change normal pipeline results.

Current production fitting still uses the lmfit path in
`fitting/mos2_core/fitting/raman_lmfit.py`. Treat lmfit output as the current
baseline for report compatibility until TASK-021 is explicitly promoted.

```powershell
.\.venv\Scripts\python.exe -m fitting.mos2_raman.compare_lsq_guardrail --raw-dir data/raw/raman/sample_A --pattern Y1-X*.txt --max-files 5
```

The runner compares current lmfit candidates against least-squares candidates for
`peak_2_model` through `peak_5_model`, then writes a candidate-level CSV under
`data/results/raman/reports/`.

Current guardrail status:
- least-squares shows a material candidate-level speedup in Raman n-peak tests.
- It is not yet a drop-in replacement: selected model agreement is only about
  `67.5%` across four 20-spectrum sample sets and `70.4%` on one full 81-spectrum grid.
- Most selected-model changes are `peak_4_model -> peak_5_model`.
- Lower RMSE/AIC from least-squares does not automatically mean it is the more
  correct scientific result; `peak_5_model` gains must be checked for physically
  meaningful LA/side-peak behavior before changing the default.

## Raman Fit Config Conventions

- `fit.two_stage_anchor` uses nested keys only:
  - `enabled`
  - `window`
- Anchor mode center coupling for Raman n>=3 models:
  - `LO = E2g - d_lo_from_e2g`
  - `ZO = A1g + d_zo_from_a1g`
  - `LA = A1g + d_la_from_a1g`
- Optional second-pass auto refinement (Raman):
  - `fit.auto_refine.enabled`
  - `fit.auto_refine.min_rmse_improvement` (fraction, `0.01` = 1%)
  - objective: `y_corr`, adopt refined candidate only when RMSE improves by threshold or more
- `raman.yaml` `fit` section is organized in execution-order blocks:
  1. ROI/comparison windows
  2. Ordering/anchor policy
  3. Anchor seeds/relative offsets
  4. Center bounds
  5. Width bounds
  6. Model priors
  7. Prefit gate

## Run GUI

```powershell
.\.venv\Scripts\python.exe -m streamlit run gui/Main.py
```

Recommended review flow in Home navigation:
- `Run Analysis -> Flagged -> All Spectra -> Finalize`

## Package (PyInstaller)

Build from repository root:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --distpath dist --workpath dist/build mos2_optical_analysis.spec
Copy-Item -Path PACKAGING_DIST_README.md -Destination dist/mos2-analysis/PACKAGING_DIST_README.md -Force
```

Packaging outputs:

- distributable: `dist/mos2-analysis`
- temporary work files: `dist/build`
- legacy fallback folders (`build/`, `build_progressfix/`, `dist_progressfix/`) are not release targets

Distribution minimum:

- ship the full `dist/mos2-analysis` folder (including `_internal`)
- include `PACKAGING_DIST_README.md` for end-user run instructions

## Manual Refit (All Spectra Viewer + Desktop Editor)

- All Spectra Viewer now supports hybrid manual correction:
  - Streamlit orchestration in browser
  - external desktop editor (`PySide6 + pyqtgraph`) for peak parameter editing
- Spectrum navigation is unified in the sidebar:
  - `Row index (Y)` moves vertically (example: `Y1-X1 -> Y2-X1`)
  - `Spectrum index (X)` moves horizontally (example: `Y1-X1 -> Y1-X2`)
  - main-area row jump buttons were removed to avoid index conflicts
- Graph styling is centralized in `fitting/mos2_raman/config/raman_graph.yaml`:
  - raw/fitted/baseline/component colors are shared across All Spectra and Manual Refit preview
  - fitted curves are rendered on a denser x-grid for smoother display
- From **All Spectra Viewer**, click `Open Manual Editor (Desktop)` on current spectrum.
- From **All Spectra Viewer**, candidate model dropdown also provides `Apply Model Override` for manual model selection.
- In desktop editor:
  - switch interaction mode with top icon buttons: `Move` / `Zoom` / `Edit`
  - initial x-range and autoscale use the same rule as All Spectra main graph (`e2g/a1g +/- peak_padding`, fallback from `raman_graph.yaml`)
  - in `Edit` mode, handles are split by role:
    - left handle: `fraction` (`eta`, Gaussian<->Lorentzian mix)
    - top handle: `center` (left/right) + `height` (up/down)
    - right handle: `FWHM`
  - right-click menu includes `Autoscale (Main View)` (also available by double-click in `Zoom` mode)
  - live preview metrics show `RMSE` / `AIC` and delta vs before-fit values
  - preview/manual synthesis uses lmfit-consistent area-normalized line-shape math (`gaussian/lorentz/pvoigt`)
  - `Auto Fit (Use Current as Initial)` runs one-spectrum re-fit from current edited peaks
  - edit `fraction`, `center`, `height`, `fwhm`, and fix flags for all four (`Fix F`, `Fix C`, `Fix H`, `Fix W`)
  - toggling fix flags keeps the current zoom window (no auto-reset)
  - click `Save and Close`
- Back in Streamlit:
  - one-spectrum refit runs via `SingleSpectrumRefitAPI`
  - before/after overlay and metrics are shown
  - manual override is saved to `data/results/{raman,pl}/manual_refits/{run_id}_manual_overrides.json`
  - request/response IPC JSON files are temporary runtime artifacts and are not kept as durable result files

Direct desktop editor launch:

```powershell
.\.venv\Scripts\python.exe -m gui.desktop_editor.app --request <request.json> --output <response.json>
```

If desktop launch fails with `PySide6 import failed`, reinstall dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run Analysis Page

- `Run type = Single folder`
  - selected folder is executed once
  - user `Run ID` is used as report prefix
- `Run type = Batch (immediate subfolders)`
  - selected folder is treated as parent
  - each immediate subfolder with matching spectrum files is executed
  - each subfolder name becomes `run-id`
- `Result Bin (optional)` in Run Analysis
  - selectable items are report JSON + manual override JSON
  - when report JSON is selected, paired CSV and matching manual override JSON are linked automatically
  - move selected set into `data/bin/results/{modality}` first (soft delete)
  - restore from Bin when needed
  - permanently delete later from Bin with explicit confirmation
- `Progress every N files` controls log update frequency from pipeline
- `Pattern` defaults to `*.txt` for Raman and `*.asc` for PL.
- `PL Model Options` can keep the YAML model ensemble (`auto`) or force `pl_single_pvoigt`, `pl_a_doublet_pvoigt`, or `pl_5_component_pvoigt`.
- `Raman Advanced Options` in Run Analysis:
  - `peak_n_mode`: choose auto or fixed model (`peak_2_model` ~ `peak_5_model`)
  - `distance_outlier`: config/enabled/disabled
  - `delta_outlier`: config/enabled/disabled
  - `si_calibration`: config/enabled/disabled (Si peak based x-offset correction on/off)
- live run status focuses on `fit`:
  - single mode: one `Fit Progress` card (`valid/attention/invalid`, `elapsed`, `eta`)
  - batch mode: `Overall (fit only)` + `Current Fit` progress, with current batch/folder/file hints
- raw stdout lines are available in `Raw Logs (advanced)`

## Output Paths

- Raman: `data/results/raman/reports`
- PL: `data/results/pl/reports`
- report JSON `spectra[]` rows now include full selected-fit details:
  - flattened selected `params` + `metrics`
  - nested snapshots as `fit_params` and `fit_metrics`
  - PL metadata fields `temperature_k` and `treatment_label` when they can be inferred from folder/file names
  - PL intensity-conversion metadata when intensity density correction is enabled
  - `all_candidates` for preserving non-selected PL candidates such as the A-/A0 doublet alongside the five-component fit

## Report Discovery Rule (GUI)

GUI pages read reports only from:
- `data/results/raman/reports`
- `data/results/pl/reports`
