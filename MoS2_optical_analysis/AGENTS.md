# AGENTS.md (MoS2 Fit Workspace)

This guide defines safe working conventions for the migrated workspace.

## Active Structure

- `fitting/mos2_core`: shared pipeline modules
- `fitting/mos2_raman`: Raman entrypoints and config
- `fitting/mos2_pl`: PL entrypoints and config
- `gui`: Streamlit UI
- `data/raw`, `data/bin/results`, `data/results`: runtime I/O

## Required References

- Before starting implementation, read `ARCHITECTURE.md` and `task_agents.md`.
- Use them as the source of truth for current structure, task boundaries, and validation scope.
- If code behavior and docs differ, update docs and code together in the same change.

## Fast Commands

Run from workspace root (`MoS2_optical_analysis`):

```powershell
# Raman
.\.venv\Scripts\python.exe -m fitting.mos2_raman.run_dummy_pipeline
.\.venv\Scripts\python.exe -m fitting.mos2_raman.run_raw_pipeline --raw-dir data/raw/raman/... --run-id my_raman
.\.venv\Scripts\python.exe -m fitting.mos2_raman.run_raw_pipeline --raw-dir data/raw/raman/... --batch-subdirs

# PL
.\.venv\Scripts\python.exe -m fitting.mos2_pl.run_dummy_pipeline
.\.venv\Scripts\python.exe -m fitting.mos2_pl.run_raw_pipeline --raw-dir data/raw/pl/... --run-id my_pl
.\.venv\Scripts\python.exe -m fitting.mos2_pl.run_raw_pipeline --raw-dir data/raw/pl/... --batch-subdirs

# GUI
.\.venv\Scripts\python.exe -m streamlit run gui/Main.py

# Desktop editor (manual refit)
.\.venv\Scripts\python.exe -m gui.desktop_editor.app --request <request.json> --output <response.json>
```

## Run Analysis UI Rules

- `Run type = single`: runs selected folder with `--run-id`.
- `Run type = batch_subdirs`: treats selected folder as parent and runs immediate subfolders that match `--pattern`.
- In batch mode, each subfolder name is used as run-id.
- Raman advanced runtime toggles in Run Analysis:
  - `peak_n_mode`
  - `distance_outlier`
  - `delta_outlier`
  - `si_calibration`
- Live status UI shows `fit/select/review` stage cards and keeps raw logs in the advanced expander.
- Data delete workflow is soft-delete first: move selected result files to `data/bin/results/{modality}`.
- In `A) Move Result Files to Bin`, selectable result items are JSON only:
  - `reports/*_fit_report.json`
  - `manual_refits/*_manual_overrides.json`
- When a report JSON is moved/restored/purged, paired CSV + matching override JSON are linked and processed together.
- Bin entries can be restored or permanently deleted later with explicit confirmation.

## Manual Refit UI Rules

- Desktop editor `Edit` mode handle ownership:
  - left handle adjusts `fraction` (`eta`, Gaussian<->Lorentzian mix)
  - top handle adjusts `center` + `height`
  - right handle adjusts `FWHM`
- Mode switching is exposed as top icon buttons (`Move`, `Zoom`, `Edit`).
- Peak table includes editable `fraction` with full fix flags: `Fix F`, `Fix C`, `Fix H`, `Fix W`.
- Toggling any fix flag must preserve current zoom/view state.

## Output Contracts

- Raman reports: `data/results/raman/reports/*_fit_report.json`
- PL reports: `data/results/pl/reports/*_fit_report.json`
- CSV pairs: `*_fit_parameters.csv`
- Manual override records: `data/results/{raman,pl}/manual_refits/{run_id}_manual_overrides.json`
- `fit_status` domain: `valid | attention | invalid`

## Editing Rules

- Prefer editing shared behavior in `fitting/mos2_core`.
- Keep modality-specific behavior in `fitting/mos2_raman` or `fitting/mos2_pl`.
- Keep GUI path logic in `gui/components/report_loader.py`.
- Do not add runtime path dependencies to `legacy/`, `mos2_raman/`, or `mos2_spectra_pipeline/`.

## Git Workflow Rules

- Default workflow for Codex:
  1. create a task-scoped branch before edits (`chore/...`, `feat/...`, `fix/...`, `exp/...`)
  2. apply code/docs updates
  3. commit changes with a concise scoped message
- Keep docs and code in the same commit when behavior changes.
- Keep commits small and reversible; avoid mixing unrelated changes.
- If user explicitly requests no commit/branch for a task, follow user request.

## Raman Config Rules

- Keep `fit.two_stage_anchor` in nested form only (`enabled`, `window`).
- Keep optional `fit.auto_refine` in nested form (`enabled`, `min_rmse_improvement`).
- Keep `fitting/mos2_raman/config/raman.yaml` and `fitting/mos2_pl/config/raman.yaml` `fit` block ordering aligned.
- In anchor mode docs/code, describe center coupling as anchor-centric:
  - `LO = E2g - d_lo_from_e2g`
  - `ZO = A1g + d_zo_from_a1g`
  - `LA = A1g + d_la_from_a1g`

## Build/Packaging Policy

- Do not run packaging/build commands (for example, `PyInstaller`) unless the user explicitly asks for a build in the current request.
- If packaging-related files are edited but no explicit build request is given, stop at code/doc updates and report what changed without building.
- Standard packaging layout:
  - distributable folder: `dist/mos2-analysis`
  - temporary work folder: `dist/build`
- `dist_progressfix` / `build_progressfix` are temporary fallback names and must not be the default distribution target.

## Minimal Validation Required

After changes, run at least:

1. Raman dummy pipeline
2. PL dummy pipeline
3. Raman raw single-folder run (`run_raw_pipeline --raw-dir ... --run-id ...`)
4. Raman or PL batch run (`run_raw_pipeline --raw-dir ... --batch-subdirs`)
5. GUI launch (`streamlit run gui/Main.py`) and HTTP reachability check
6. All Spectra Viewer smoke check with a filter resulting in exactly one row
7. Manual refit API smoke (`SingleSpectrumRefitAPI`) with one report row
