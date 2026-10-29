# Task Agents (Current Work Tracking)

## Purpose
`task_agents.md` is a tool for centrally managing current tasks and agent responsibilities. It records status for each task and specifies links to `agents.md` policies and `architecture.md` impacts.

## Format
- Task ID: short key (e.g., TASK-001)
- Title
- Description
- Assigned Agent
- Related Files
- Status: Todo / In Progress / Done
- Expected Impact (whether to reflect in architecture.md)

## Task List

### TASK-001: Refactor `mos2_spectra_pipeline` to `mos2_raman`
- Description: Move existing Raman codebase to new separated location and update module paths
- Assigned: raman_pl_agent
- Related Files:
  - `mos2_spectra_pipeline/...`
  - `agents.md` (policies)
  - `architecture.md` (structure updates)
- Status: Done
- Impact: high (directory structure change)
- Sub-steps:
  1. Create `legacy/` directory at root level and copy entire `mos2_spectra_pipeline/` as backup
  2. Create `mos2_raman/` directory at root level
  3. Copy entire `mos2_spectra_pipeline/` contents to `mos2_raman/`
  4. Update all Python import statements from `mos2_spectra_pipeline` to `mos2_raman`
  5. Update entry point scripts (`run_dummy_pipeline.py`, `run_raw_pipeline.py`) to use new paths
  6. Update Streamlit app imports in `app/`
  7. Test pipeline execution with dummy data
- Prerequisites:
  - Backup current `mos2_spectra_pipeline/` directory
  - Ensure no active processes using the old paths
  - Run `run_dummy_pipeline` successfully before starting
- Risks:
  - Import errors causing module not found exceptions
  - Data path references breaking (e.g., in config files)
  - Streamlit app failing to load due to path changes
- Success Criteria:
  - All Python files import without errors
  - `run_dummy_pipeline` executes successfully
  - Streamlit app starts without import issues
  - No broken links in config or data paths

### TASK-002: Enable PL mode pipeline
- Description: Add modality branching in `src/fitting/raman_lmfit.py`, connect `config/pl.yaml`
- Assigned: raman_pl_agent
- Related Files:
  - `src/fitting/raman_lmfit.py`
  - `src/core/default_stages.py`
  - `config/pl.yaml`
- Status: Done
- Impact: medium
- Sub-steps:
  1. Review `config/pl.yaml` for PL-specific parameters
  2. Add modality check in `raman_lmfit.py` run method (if modality == "PL")
  3. Implement PL-specific fitting logic (e.g., different peak models)
  4. Update `default_stages.py` to conditionally use PL fitter
  5. Test PL pipeline with dummy data
- Prerequisites:
  - `config/pl.yaml` is complete and validated
  - Understand current Raman fitting implementation
  - Run existing Raman pipeline successfully
- Risks:
  - PL fitting logic may not converge or produce invalid results
  - Breaking changes to shared fitting interfaces
  - Config loading errors for PL mode
- Success Criteria:
  - PL mode pipeline runs without errors
  - Fit results include PL-specific parameters
  - `fit_status` values remain valid
  - JSON/CSV reports generated correctly

### TASK-003: Structure `results/` folders by `raman/pl`
- Description: Separate result output folders based on modality
- Assigned: raman_pl_agent
- Related Files:
  - `results/`
  - `analysis/reporting.py`
- Status: Done
- Impact: medium
- Sub-steps:
  1. Modify `reporting.py` to create modality-specific subdirectories (e.g., `results/raman/`, `results/pl/`)
  2. Update output paths in reporting functions
  3. Ensure backward compatibility or migration for existing results
  4. Update Streamlit app to load from new paths
  5. Test report generation for both modalities
- Prerequisites:
  - Understand current reporting output structure
  - Backup existing `results/` directory
  - Confirm modality is available in pipeline context
- Risks:
  - Existing reports become inaccessible
  - Streamlit visualization breaks due to path changes
  - File naming conflicts between modalities
- Success Criteria:
  - Reports saved to `results/{modality}/` subfolders
  - Streamlit app loads reports from new locations
  - No data loss from existing results
  - Both Raman and PL reports generate correctly

### TASK-004: Review and update architecture documentation
- Description: After major refactoring, reflect main flows and paths in `architecture.md`
- Assigned: raman_pl_agent
- Related Files:
  - `ARCHITECTURE.md`
- Status: Done
- Impact: low
- Sub-steps:
  1. Review changes from TASK-001, TASK-002, TASK-003
  2. Update directory structure section in `ARCHITECTURE.md`
  3. Update data flow diagrams to include modality branching
  4. Add new extension points for PL support
  5. Validate all links and references are accurate
- Prerequisites:
  - Completion of TASK-001 through TASK-003
  - Access to updated codebase structure
- Risks:
  - Documentation becoming outdated if changes continue
  - Inaccurate descriptions leading to confusion
- Success Criteria:
  - `ARCHITECTURE.md` accurately reflects current structure
  - All referenced files and paths exist
  - Documentation is clear and actionable for new contributors

### TASK-005: Streamlit actual browser run verification
- Description: Run Streamlit app in real browser and verify page loading/report browsing for current outputs
- Assigned: raman_pl_agent
- Related Files:
  - `gui/Main.py`
  - `gui/components/report_loader.py`
  - `gui/pages/*.py`
  - `task_agents.md`
- Status: Done
- Impact: medium
- Sub-steps:
  1. Confirm Raman/PL reports exist under `results/{modality}/reports`
  2. Launch Streamlit server from workspace root
  3. Open local URL in browser and verify home load
  4. Check report selection and basic page navigation
  5. Fix blockers with minimum code changes if needed
  6. Re-run and record final status
- Prerequisites:
  - `.venv` with Streamlit dependencies
  - at least one report JSON available
- Risks:
  - browser launch limitation in sandboxed runtime
  - schema mismatch with legacy reports causing page errors
  - local port conflicts
- Success Criteria:
  - Streamlit server starts without runtime errors
  - local browser launch command succeeds
  - report-loading flow is reachable
  - TASK-005 execution notes are documented

### TASK-006: Create target top-level structure (`fitting` / `gui` / `data`)
- Description: Introduce new project structure without breaking current runtime behavior
- Assigned: raman_pl_agent
- Related Files:
  - workspace root directories
  - `mos2_raman/`
  - `legacy/mos2_spectra_pipeline/`
- Status: Done
- Impact: high (repository layout change)
- Sub-steps:
  1. Create `fitting/mos2_core`, `fitting/mos2_raman`, `fitting/mos2_pl`, `gui`, `data/raw/raman`, `data/raw/pl`, `data/results/raman`, `data/results/pl`
  2. Copy current implementation into target layout in a non-destructive way
  3. Keep temporary compatibility paths to avoid immediate breakage
  4. Verify directory contracts and file presence
- Prerequisites:
  - Existing backups remain intact (`legacy/...`)
  - TASK-001~005 completed
- Risks:
  - Partial move can create mixed-path confusion
  - Hidden path assumptions in scripts/docs
- Success Criteria:
  - New directory skeleton exists as agreed
  - No data/code loss
  - Compatibility fallback paths documented

### TASK-007: Refactor imports and pipeline entrypoints to `fitting/*`
- Description: Rewire code imports and runtime paths to the new `fitting/mos2_*` layout
- Assigned: raman_pl_agent
- Related Files:
  - `fitting/mos2_core/**`
  - `fitting/mos2_raman/**`
  - `fitting/mos2_pl/**`
  - entrypoint scripts and config loaders
- Status: Done
- Impact: high (execution path change)
- Sub-steps:
  1. Update module imports and package init files for new layout
  2. Update run entrypoints and config resolution paths
  3. Run compile checks and smoke runs (Raman/PL)
  4. Fix regressions and remove obsolete import bridges when safe
- Prerequisites:
  - TASK-006 completed
- Risks:
  - `ModuleNotFoundError` due to stale paths
  - accidental contract break across core types/interfaces
- Success Criteria:
  - Raman and PL smoke runs pass from new package paths
  - No critical import errors remain
  - Core contracts remain valid

### TASK-008: Move GUI and data routing to new root (`gui`, `data`)
- Description: Finalize Streamlit and data/result paths to `gui/` and `data/{raw,results}` structure
- Assigned: raman_pl_agent
- Related Files:
  - `gui/**`
  - `data/raw/**`
  - `data/results/**`
  - report loaders and documentation files
- Status: Done
- Impact: medium
- Sub-steps:
  1. Move Streamlit app code to `gui/` and update launch command/docs
  2. Point loaders/writers to `data/results/{raman,pl}`
  3. Align raw data discovery to `data/raw/{raman,pl}`
  4. Run Streamlit + pipeline end-to-end validation
  5. Update `ARCHITECTURE.md`, `agents.md`, and task notes
- Prerequisites:
  - TASK-007 completed
- Risks:
  - Legacy reports not found if migration map is incomplete
  - UI pages breaking from path/schema mismatch
- Success Criteria:
  - GUI starts from `gui/` path
  - Raman/PL reports read/write under `data/results/*`
  - Docs reflect final structure and run commands

### TASK-009: Define hybrid manual-refit contract (Streamlit launcher <-> PySide6 editor)
- Description: Specify request/response JSON contract and module boundaries for hybrid manual refit workflow
- Assigned: raman_pl_agent
- Related Files:
  - `AGENTS.md`
  - `ARCHITECTURE.md`
  - `task_agents.md`
  - `gui/pages/3_All_Spectra_Viewer.py`
  - `fitting/mos2_core/review/refit_api.py`
- Status: Done
- Impact: medium (architecture contract addition)
- Sub-steps:
  1. Define request JSON schema from Streamlit to desktop editor (`report_path`, `spectrum_id`, `modality`, current params)
  2. Define response JSON schema from desktop editor back to Streamlit (`overrides`, `refit_result`, metadata)
  3. Fix storage contract for manual corrections under `data/results/{modality}/manual_refits`
  4. Document strict responsibility split (GUI/orchestrator vs backend refit API vs desktop UI)
- Prerequisites:
  - TASK-008 completed
  - Current report row schema confirmed from All Spectra Viewer
- Risks:
  - Ambiguous contract causing launcher/editor mismatch
  - Schema drift from current report payload
- Success Criteria:
  - Contract fields and paths are finalized and documented
  - No legacy/old-path references included
  - Follow-up implementation tasks can proceed without schema ambiguity

### TASK-010: Build PySide6 + pyqtgraph desktop editor MVP shell
- Description: Add external desktop editor process for one-spectrum manual correction UI (without replacing Streamlit)
- Assigned: raman_pl_agent
- Related Files:
  - `gui/desktop_editor/app.py`
  - `gui/desktop_editor/main_window.py`
  - `gui/desktop_editor/plot_widget.py`
  - `gui/desktop_editor/peak_table.py`
  - `gui/desktop_editor/controller.py`
  - `gui/desktop_editor/models.py`
  - `requirements.txt`
- Status: Done
- Impact: high (new desktop UI module)
- Sub-steps:
  1. Create desktop editor package skeleton and CLI entry (`--request`, `--output`)
  2. Render one spectrum with pyqtgraph (raw + fit overlay placeholders)
  3. Implement editable peak table fields (`center`, `height`, `fwhm`, fixed flags)
  4. Add save action to output response JSON for Streamlit consumption
- Prerequisites:
  - TASK-009 contract finalized
  - PySide6/pyqtgraph dependency policy agreed
- Risks:
  - Event-loop/process lifecycle issues in desktop launch
  - Environment dependency mismatch for Qt stack
- Success Criteria:
  - Desktop editor launches with request JSON
  - User can edit one spectrum and write valid response JSON
  - Streamlit-independent editor smoke run succeeds

### TASK-011: Implement reusable single-spectrum manual refit backend API
- Description: Replace NoOp manual refit stub with real single-spectrum refit API reusing existing lmfit engine logic
- Assigned: raman_pl_agent
- Related Files:
  - `fitting/mos2_core/review/refit_api.py`
  - `fitting/mos2_core/fitting/raman_lmfit.py`
  - `fitting/mos2_core/core/types.py`
  - `fitting/mos2_core/review/` (adapter/helper modules as needed)
- Status: Done
- Impact: high (manual refit backend capability)
- Sub-steps:
  1. Define API input/output dataclasses compatible with TASK-009 contract
  2. Map UI override parameters into engine-compatible refit inputs
  3. Execute single-spectrum refit and return report-compatible params/metrics/fitted_y
  4. Add error handling payloads for invalid inputs and fit failures
- Prerequisites:
  - TASK-009 completed
  - Existing model/candidate parameter semantics validated
- Risks:
  - Divergence between manual refit output and report schema
  - Unintended side-effects on default batch pipeline behavior
- Success Criteria:
  - API returns deterministic refit result for one spectrum
  - Existing pipeline path remains unchanged for normal runs
  - Output is consumable by both desktop editor and Streamlit page

### TASK-012: Integrate All Spectra Viewer launcher + before/after visualization
- Description: Add Streamlit-side orchestration to open desktop editor, ingest result, and visualize before/after refit
- Assigned: raman_pl_agent
- Related Files:
  - `gui/pages/3_All_Spectra_Viewer.py`
  - `gui/components/spectrum_viewer.py`
  - `gui/components/report_loader.py` (if path helpers are needed)
- Status: Done
- Impact: high (new user workflow in primary viewer)
- Sub-steps:
  1. Add `Open Manual Editor (PySide6)` action on selected spectrum
  2. Write request JSON and launch desktop process via subprocess
  3. Ingest output JSON and render before/after metrics + curve overlay
  4. Provide robust UI status for launch errors / timeout / malformed response
- Prerequisites:
  - TASK-010 completed
  - TASK-011 completed
- Risks:
  - Cross-process file handoff race conditions
  - UX confusion if editor response is partially missing
- Success Criteria:
  - User can launch editor from All Spectra Viewer and return results
  - Before/after comparison appears in Streamlit for selected spectrum
  - Failure states are user-readable and non-destructive

### TASK-013: Persist manual corrections + docs and validation
- Description: Finalize JSONL persistence under results tree and update docs/tests for hybrid workflow
- Assigned: raman_pl_agent
- Related Files:
  - `data/results/{raman,pl}/manual_refits/` (runtime output contract)
  - `fitting/mos2_core/review/decision_store.py` (or new manual refit store module)
  - `README.md`
  - `ARCHITECTURE.md`
  - `AGENTS.md`
  - `task_agents.md`
- Status: Done
- Impact: medium
- Sub-steps:
  1. Append manual correction records to JSONL with schema version + timestamps
  2. Add download/export hooks for per-spectrum correction payload in GUI
  3. Update docs for hybrid launch, storage paths, and operator flow
  4. Run compile + Streamlit smoke + one end-to-end manual correction scenario
- Prerequisites:
  - TASK-012 completed
- Risks:
  - File growth/duplication in JSONL logs
  - Inconsistent correction schema across releases
- Success Criteria:
  - Manual corrections are persisted in stable JSONL schema
  - Docs and architecture reflect actual implemented workflow
  - Validation checklist passes for hybrid path

### TASK-014: Unify All Spectra/Manual Refit graph styling and fitted-curve rendering
- Description: Consolidate graph color/style config in `raman_graph.yaml` and improve fitted-curve visual quality in All Spectra + Manual Refit previews
- Assigned: raman_pl_agent
- Related Files:
  - `fitting/mos2_raman/config/raman_graph.yaml`
  - `gui/components/spectrum_viewer.py`
  - `gui/pages/3_All_Spectra_Viewer.py`
  - `gui/desktop_editor/plot_widget.py` (if desktop preview style needs the same palette)
  - `README.md`
  - `ARCHITECTURE.md`
- Status: Done
- Impact: medium (UI consistency + readability)
- Sub-steps:
  1. Add centralized color tokens to `raman_graph.yaml` for raw/fitted/baseline/components/markers.
  2. Update graph rendering paths to read color/style from config instead of hardcoded values.
  3. Render fitted curve with denser/interpolated x-grid (not forced to raw point count) for smoother line quality.
  4. In manual refit preview, ensure raw + fitted are overlaid in one view and baseline is explicitly drawn.
  5. Keep main graph and manual refit graph color mapping identical via shared config keys.
- Prerequisites:
  - Existing graph config loader path (`load_graph_config`) remains stable.
  - Current report payload keeps required fitted/baseline parameters.
- Risks:
  - Config-key mismatch can break rendering defaults.
  - Over-smoothing may visually hide local fit errors if interpolation is too aggressive.
- Success Criteria:
  - Main graph and manual refit graph use the same configured colors.
  - Baseline is visible in manual refit preview overlay.
  - Fitted line appears smoother while preserving fit shape and alignment.
  - No regression for legacy reports missing optional graph fields.

### TASK-015: Enhance Manual Refit editor interaction modes and drag handles
- Description: Add explicit interaction modes and direct-manipulation handles for center/height/FWHM editing in manual refit UI
- Assigned: raman_pl_agent
- Related Files:
  - `gui/desktop_editor/main_window.py`
  - `gui/desktop_editor/controller.py`
  - `gui/desktop_editor/plot_widget.py`
  - `gui/desktop_editor/models.py`
  - `gui/desktop_editor/peak_table.py`
  - `gui/components/manual_refit_contract.py` (if new UI fields are persisted)
  - `README.md`
  - `ARCHITECTURE.md`
- Status: Done
- Impact: high (core manual editing UX change)
- Sub-steps:
  1. Add mode switch UI: `Move`(drag pan), `Zoom`(drag-rect zoom), `Edit`(parameter drag edit).
  2. In `Edit` mode, add draggable peak-top handle for center (x drag) and height (y drag).
  3. Add two draggable half-maximum handles (left/right) to control FWHM directly.
  4. Synchronize drag edits with peak table values and keep bidirectional update consistency.
  5. Add guardrails (min FWHM, finite bounds, snap/clip behavior) and visual cues for active handles.
- Prerequisites:
  - TASK-010/011/012 manual refit flow remains functional.
  - pyqtgraph interaction callbacks are stable in current runtime environment.
- Risks:
  - Mode-conflict bugs (pan/zoom/edit event overlap).
  - Unintended parameter jumps from handle mis-binding or coordinate transform errors.
- Success Criteria:
  - Operator can switch modes without event conflicts.
  - Peak-top and half-maximum handles update center/height/FWHM as expected.
  - Updated parameters are reflected in table and serialized response payload correctly.
  - Manual refit smoke flow remains stable after interaction upgrade.

### TASK-016: Add PyInstaller packaging setup for mixed Streamlit + pipeline + desktop editor app
- Description: Create project-specific PyInstaller spec with frozen-compatible subprocess launchers
- Assigned: raman_pl_agent
- Related Files:
  - `mos2_optical_analysis.spec`
  - `packaging/entry_streamlit.py`
  - `packaging/entry_run_raman.py`
  - `packaging/entry_run_pl.py`
  - `packaging/entry_desktop_editor.py`
  - `gui/pages/1_Run_Analysis.py`
  - `gui/pages/3_All_Spectra_Viewer.py`
  - `PACKAGING_PYINSTALLER.md`
- Status: Done
- Impact: medium (distribution/build workflow)
- Sub-steps:
  1. Inspect real entrypoints and resource/config layout.
  2. Add dedicated frozen launchers for Streamlit and subprocess worker targets.
  3. Build multi-target one-folder PyInstaller spec for app + workers.
  4. Exclude runtime-generated result outputs from bundled datas.
  5. Add packaging notes and build command docs.
- Prerequisites:
  - TASK-008~015 runtime structure remains stable.
- Risks:
  - Streamlit dynamic imports can cause hidden-import misses in frozen builds.
  - Frozen subprocess behavior can fail if worker executables are not bundled.
- Success Criteria:
  - Spec file matches repository paths and mixed runtime model.
  - Run Analysis and manual editor launch paths remain valid in frozen mode.
  - Packaging docs clearly define included vs excluded runtime data.

### TASK-017: Standardize distribution layout and end-user packaging guide
- Description: Clean up packaging output conventions and ensure distributable bundle includes minimal end-user usage instructions
- Assigned: raman_pl_agent
- Related Files:
  - `task_agents.md`
  - `PACKAGING_PYINSTALLER.md`
  - `README.md`
  - `mos2_optical_analysis.spec`
  - `PACKAGING_DIST_README.md`
  - `AGENTS.md`
- Status: Done
- Impact: medium (distribution UX + release process clarity)
- Sub-steps:
  1. Standardize packaging paths to `dist/mos2-analysis` (deliverable) and `dist/build` (temporary work output).
  2. Define `dist_progressfix` / `build_progressfix` as temporary fallback-only outputs and remove them from default release flow.
  3. Ensure distribution includes minimal end-user guide for launch, port handling, and CLI examples.
  4. Confirm packaging docs and policy docs are aligned on build/distribute workflow.
- Prerequisites:
  - TASK-016 completed
- Risks:
  - Confusion from mixed output folder naming in release artifacts
  - End users missing run instructions when only executables are delivered
- Success Criteria:
  - One canonical distribution layout is documented and used
  - Temporary fallback folders are not treated as default deliverables
  - Distributable folder always includes a minimal usage README

### TASK-018: Reorder navigation to show Flagged Spectra before All Spectra Viewer
- Description: Change main navigation order so triage starts from flagged items, then detailed per-spectrum inspection
- Assigned: raman_pl_agent
- Related Files:
  - `task_agents.md`
  - `gui/Main.py`
  - `README.md`
  - `ARCHITECTURE.md`
- Status: Done
- Impact: low (navigation UX flow)
- Sub-steps:
  1. Swap page-link order in `gui/Main.py` so `2_Flagged_Spectra.py` is shown before `3_All_Spectra_Viewer.py`.
  2. Verify sidebar/top navigation labels and numbering reflect the new order consistently.
  3. Update user-facing docs that describe page order or recommended review flow.
- Prerequisites:
  - Existing report-loading flow remains unchanged
- Risks:
  - Minor user confusion if docs and UI order diverge
- Success Criteria:
  - UI order is `Run Analysis -> Flagged Spectra -> All Spectra Viewer` for the relevant section
  - Docs mention flagged-first triage flow
  - No regression in page routing

### TASK-019: MVP manual-override unification + cross-view projection + bin linkage
- Description: Unify manual changes into one override JSON per report, apply projection in all viewers, and link report JSON move/delete with paired CSV and override JSON
- Assigned: raman_pl_agent
- Related Files:
  - `task_agents.md`
  - `gui/components/report_loader.py`
  - `gui/pages/1_Run_Analysis.py`
  - `gui/pages/3_All_Spectra_Viewer.py`
  - `gui/pages/4_Map_Viewer.py`
  - `gui/pages/5_Model_Comparison.py`
  - `gui/pages/6_Sample_Comparison.py`
  - `gui/pages/7_Finalize.py`
  - `fitting/mos2_core/review/manual_overrides.py`
  - `fitting/mos2_core/review/refit_api.py`
  - `gui/components/data_bin.py`
  - `README.md`
  - `ARCHITECTURE.md`
  - `AGENTS.md`
- Status: Done
- Impact: high (manual-edit data contract + cross-page consistency + delete/bin behavior)
- Sub-steps:
  1. JSON unification: stop persisting `request/editor_response/bundle` as durable artifacts and standardize one override file per report:
     - `data/results/{modality}/manual_refits/{run_id}_manual_overrides.json`
  2. Define and adopt override schema `manual_overrides.v1` with per-spectrum latest-write semantics (`updated_at_utc`) and `action_type` (`model_override|manual_refit|autofit`).
  3. Add projection logic in common report load path (`report_loader.py`) so `load_report_payload()` always merges report JSON + override JSON before returning payload/dataframe.
  4. Ensure projected results are reflected consistently across:
     - `3_All_Spectra_Viewer.py`
     - `4_Map_Viewer.py`
     - `5_Model_Comparison.py`
     - `6_Sample_Comparison.py`
     - `7_Finalize.py`
  5. Add manual model-selection path in All Spectra Viewer (`Apply Model Override`) while keeping AIC auto-selection as default behavior.
  6. Bin/delete linkage rule:
     - when report JSON is moved/restored/purged, process paired CSV + matching override JSON together as one set.
     - set mapping: `{run_id}_fit_report.json` <-> `{run_id}_fit_parameters.csv` <-> `{run_id}_manual_overrides.json`
  7. Run Analysis > `A) Move Result Files to Bin` selection list policy:
     - show only `*_fit_report.json` and `*_manual_overrides.json`
     - hide CSV from direct selection and handle CSV only via linked action with report JSON.
- Prerequisites:
  - TASK-018 does not block this task but can be merged in the same UX validation pass.
  - Existing report naming convention (`*_fit_report.json`, `*_fit_parameters.csv`) remains stable.
- Risks:
  - Schema drift between legacy `manual_refits.jsonl` records and new unified override format.
  - Cache invalidation issues causing some pages to show stale pre-override data.
  - Incomplete linked delete/restore behavior causing orphaned CSV/override files.
- Success Criteria:
  - Manual updates are persisted in one canonical override JSON per report.
  - Page navigation after manual update shows consistent values in Map/Model/Sample/Finalize.
  - Durable `request/editor_response/bundle` files are not left behind.
  - Report JSON bin move/delete always moves/deletes paired CSV + override JSON together.
  - Bin selection UI displays only report JSON + override JSON entries.

### TASK-020: Spectrum-level multiprocessing for fit stage
- Description: Introduce spectrum-level multiprocessing in fitting to reduce end-to-end runtime while preserving current model coverage and fit behavior
- Assigned: raman_pl_agent
- Related Files:
  - `task_agents.md`
  - `fitting/mos2_core/fitting/raman_lmfit.py`
  - `fitting/mos2_raman/run_raw_pipeline.py`
  - `fitting/mos2_pl/run_raw_pipeline.py`
  - `fitting/mos2_core/core/default_stages.py`
  - `README.md`
  - `ARCHITECTURE.md`
  - `AGENTS.md`
- Status: Done
- Impact: high (fit runtime performance + execution model)
- Sub-steps:
  1. Add worker-count runtime option (for example `--workers`) with safe default (`1`) to preserve current sequential behavior.
  2. Refactor fit-stage per-spectrum execution into a top-level worker function compatible with Windows multiprocessing pickling.
  3. Execute spectrum fits via `ProcessPoolExecutor` when `workers > 1` and merge results deterministically in input order.
  4. Preserve current progress/log contract (`[fit] ...`) and status aggregation (`valid/attention/invalid`) in both sequential and parallel modes.
  5. Add process-safety defaults for nested numeric threading (`OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`) when multiprocessing is enabled.
  6. Validate parity of key outputs (selected model, RMSE/AIC/BIC, fit_status counts, report schema) between `workers=1` and `workers>1`.
- Prerequisites:
  - Current fit contracts from TASK-019 remain stable.
  - No behavior changes to model list/selection policy in this task.
- Risks:
  - Serialization/pickling issues for non-top-level functions or non-picklable objects.
  - Progress updates becoming noisy or out-of-order in parallel runs.
  - Oversubscription regressions if internal BLAS/OpenMP threading is not controlled.
- Success Criteria:
  - `workers>1` run completes without regressions on Raman/PL smoke inputs.
  - Report outputs remain schema-compatible and selection behavior is unchanged.
  - Measurable runtime improvement is observed on multi-spectrum datasets.

### TASK-021: Reduce fitting overhead by moving hot path from lmfit wrappers to scipy least_squares
- Description: Replace high-overhead lmfit wrapper usage in hot fitting paths with equivalent `scipy.optimize.least_squares` implementations while preserving constraints and output semantics
- Assigned: raman_pl_agent
- Related Files:
  - `task_agents.md`
  - `fitting/mos2_core/fitting/raman_lmfit.py`
  - `fitting/mos2_core/review/refit_api.py`
  - `fitting/mos2_core/fitting/model_selection.py`
  - `fitting/mos2_raman/config/raman.yaml`
  - `README.md`
  - `ARCHITECTURE.md`
  - `AGENTS.md`
- Status: In Progress
- Impact: high (core fitting engine performance + numeric behavior)
- Sub-steps:
  1. Identify hot models (`peak_2`~`peak_5`, PL single-peak variants) and define least-squares parameter vectorization for each.
  2. Port current constraint semantics (bounds, anchor/order coupling, fixed/vary flags) to least-squares residual functions.
  3. Implement conversion adapters so downstream payload remains unchanged (`params`, `metrics`, `fitted_y`, `nfev`, `fit_status` inputs).
  4. Add guardrail mode for A/B comparison (`legacy_lmfit` vs `least_squares`) to quantify parity before default switch.
  5. Run parity checks on representative reports and summarize deltas (RMSE/AIC/BIC, selected model, status counts, override/refit compatibility).
  6. Update docs/config notes for the chosen default path and fallback strategy.
- Prerequisites:
  - TASK-020 is preferred first so parallelism and solver migration can be benchmarked independently.
  - Existing report/override contracts must remain backward compatible.
- Risks:
  - Subtle constraint mismatch can change selected models or fit_status distribution.
  - Metric calculation differences can impact AIC-based ranking.
  - Manual refit/editor paths may diverge if adapter parity is incomplete.
- Success Criteria:
  - least-squares path reproduces current outputs within accepted numeric tolerance.
  - Model-selection and review outcomes remain stable on validation datasets.
  - Runtime improvement is confirmed versus current lmfit wrapper path.

### TASK-022: Modernize Configuration Management with Pydantic
- Description: Replace manual dict validation in `config_loader.py` with schema-driven Pydantic models to improve type safety, maintainability, and developer experience.
- Assigned: refactoring_agent
- Related Files:
  - `fitting/mos2_core/io/config_loader.py`
  - `fitting/mos2_core/io/models.py` (New)
- Status: Todo
- Impact: high
- Sub-steps:
  1. Define Pydantic models for Raman, PL, Baseline, and Graph configs.
  2. Implement a new loader that returns these model instances.
  3. Update downstream modules to use dot-notation (config.fit.x_min) instead of keys.
  4. Run validation on existing YAML files.

### TASK-023: Decompose `raman_lmfit.py` God Object
- Description: Split the oversized `raman_lmfit.py` (1,800+ lines) into modular, single-responsibility files (e.g., `engine.py`, `model_factory.py`, `parallel_executor.py`).
- Assigned: refactoring_agent
- Related Files:
  - `fitting/mos2_core/fitting/raman_lmfit.py`
- Status: Todo
- Impact: high
- Sub-steps:
  1. Extract peak model creation to `model_factory.py`.
  2. Move pre-fit evaluation logic to `prefit_gate.py`.
  3. Relocate multiprocessing worker logic to `parallel_executor.py`.
  4. Refactor `LmfitRamanModelEnsembleFitting` to orchestrate these new modules.

### TASK-024: Separate GUI and Business Logic via Service Layer
- Description: Extract data processing and report merging logic from `report_loader.py` into a pure-Python `report_service.py` to enable unit testing and reduce Streamlit dependency.
- Assigned: refactoring_agent
- Related Files:
  - `gui/components/report_loader.py`
  - `fitting/mos2_core/analysis/report_service.py` (New)
- Status: Todo
- Impact: medium
- Sub-steps:
  1. Create `report_service.py` to handle JSON loading and override merging.
  2. Move `apply_manual_overrides_to_payload` logic to the new service.
  3. Update `report_loader.py` to call the service layer.
  4. Verify GUI pages function correctly with the new separation.

### TASK-025: Improve PL visualization and GUI support
- Description: Enhance GUI pages and spectrum components to properly display, zoom, and review PL spectra.
- Assigned: raman_pl_agent
- Related Files:
  - `gui/components/spectrum_viewer.py`
  - `gui/pages/3_All_Spectra_Viewer.py`
  - `gui/pages/4_Map_Viewer.py`
  - `gui/Main.py`
  - `gui/components/review_table.py`
  - `gui/components/parameter_editor.py`
### TASK-026: PL Multi-Component Parameter Coupling & Despiking
- Description: Fix $A^-/A^0$ peak identity flipping, peak collapse to zero, $I_2$ boundary hits, and spike noise distortion in PL multi-component deconvolution.
- Assigned: raman_pl_agent
- Related Files:
  - `fitting/mos2_pl/config/pl.yaml`
  - `fitting/mos2_raman/config/pl.yaml`
  - `fitting/mos2_core/preprocess/basic.py`
  - `fitting/mos2_core/fitting/raman_lmfit.py`
  - `tests/test_pl_multicomponent.py`
- Status: Done
- Impact: high (PL scientific deconvolution accuracy & robustness)
- Sub-steps:
  1. Add rolling-MAD despiking filter in `basic.py` to remove cosmic-ray spikes.
  2. Implement center coupling ($A^0 = A^- + \Delta E$) in `_fit_pl_component_model`.
  3. Implement FWHM broadening coupling ($\text{FWHM}(A^-) \ge 1.05\times \text{FWHM}(A^0)$).
  4. Implement fraction sharing ($\eta_{A0} = \eta_{A-}$).
  5. Expand $I_2$ center upper bound to 1.76 eV.
  6. Re-run PL pipeline on Treatment and Pristine datasets, verifying $R^2 \ge 0.992$ and clean physical progression across all temperatures.

## Execution Notes (2026-05-20)

- TASK-021 started with a guardrail-only implementation:
  - Added `fitting/mos2_core/fitting/least_squares_hotpath.py`.
    - Implements first-pass Raman `peak_2_model`~`peak_5_model` candidates with `scipy.optimize.least_squares`.
    - Mirrors current pVoigt area/sigma/fraction math, linear baseline, sigma bounds, peak-order coupling, and anchor-centric LO/ZO/LA rules.
    - Not wired into the production pipeline default path yet.
  - Added comparison runner:
    - `python -m fitting.mos2_raman.compare_lsq_guardrail --raw-dir ... --pattern ...`
    - Writes candidate-level timing/parity CSV under `data/results/raman/reports/`.
  - Initial guardrail checks:
    - `py_compile` on new modules: pass
    - 1 spectrum, `peak_2_model`: selected model agreement `1/1`; candidate speedup `~4.51x`; RMSE delta `~1.29`
    - 1 spectrum, all n-peak models: selected model agreement `1/1`; mean candidate speedup `~4.07x`; mean absolute RMSE delta `~0.46`
    - 5 spectra, all n-peak models (`sample_A`, `Y1-X*.txt`): selected model agreement `4/5`; mean candidate speedup `~6.56x`; median candidate speedup `~4.44x`; mean absolute RMSE delta `~3.14`; max absolute RMSE delta `~18.94`
    - comparison CSV artifacts generated:
      - `data/results/raman/reports/task021_lsq_guardrail_one_spectrum.csv`
      - `data/results/raman/reports/task021_lsq_guardrail_5spectra.csv`
  - Regression validation:
    - Raman dummy pipeline: pass
    - PL dummy pipeline: pass
    - Raman raw single smoke (`sample_A`, `Y1-X1.txt`, `run_id=task021_raw_single_smoke`): pass
    - Raman batch smoke (`sample_set_1`, `Y1-X1.txt`, `--batch-subdirs`): pass
    - Streamlit GUI HTTP reachability: pass (`200`, port `8521`)
    - All Spectra Viewer AppTest single-row filter (`Y1-X1`): pass (`Filtered Rows=1`)
    - Manual refit API smoke (`SingleSpectrumRefitAPI.submit_refit` on one report row): pass (`status=ok`, `fit_status=attention`)
  - Interpretation:
    - least_squares already shows material speed improvement.
    - It is not yet parity-equivalent in every case; some differences are improved local optima vs lmfit, and at least one selected-model change was observed.
    - Next TASK-021 step should classify deltas by model/spectrum and decide acceptable tolerance or add stricter legacy-compatible optimizer settings before production integration.

## TASK-021 Broader Guardrail Results (2026-05-20)

- Additional comparison runs, production path unchanged:
  - `sample_A`, first 20 spectra:
    - selected-model agreement: `12/20` (`60.0%`)
    - mean candidate speedup: `~8.23x`; median: `~4.93x`
    - mean absolute RMSE delta: `~1.71`; max absolute RMSE delta: `~18.94`
  - `sample_B`, first 20 spectra:
    - selected-model agreement: `14/20` (`70.0%`)
    - mean candidate speedup: `~8.48x`; median: `~4.86x`
    - mean absolute RMSE delta: `~1.30`; max absolute RMSE delta: `~9.91`
  - `sample_set_2/sample_E`, first 20 spectra:
    - selected-model agreement: `16/20` (`80.0%`)
    - mean candidate speedup: `~11.81x`; median: `~5.77x`
    - mean absolute RMSE delta: `~3.16`; max absolute RMSE delta: `~30.94`
  - `sample_set_3/sample_F`, first 20 spectra:
    - selected-model agreement: `12/20` (`60.0%`)
    - mean candidate speedup: `~6.45x`; median: `~4.53x`
    - mean absolute RMSE delta: `~8.08`; max absolute RMSE delta: `~74.02`
- Aggregate across the four 20-spectrum sets:
  - spectra: `80`
  - selected-model agreement: `54/80` (`67.5%`)
  - transition counts:
    - `peak_5 -> peak_5`: `42`
    - `peak_4 -> peak_5`: `24`
    - `peak_4 -> peak_4`: `12`
    - `peak_5 -> peak_4`: `2`
  - model-level mean speedup / mean absolute RMSE delta:
    - `peak_2_model`: `~4.61x` / `~9.09`
    - `peak_3_model`: `~4.11x` / `~2.68`
    - `peak_4_model`: `~13.89x` / `~0.73`
    - `peak_5_model`: `~12.36x` / `~1.76`
- Full-grid check on `sample_A` (`81` spectra):
  - selected-model agreement: `57/81` (`70.4%`)
  - mean candidate speedup: `~8.73x`; median: `~4.85x`
  - mean absolute RMSE delta: `~1.07`; max absolute RMSE delta: `~18.94`
  - mean least-squares `nfev`: `~24.8`; max least-squares `nfev`: `101`
  - transition counts:
    - `peak_5 -> peak_5`: `50`
    - `peak_4 -> peak_5`: `22`
    - `peak_4 -> peak_4`: `7`
    - `peak_5 -> peak_4`: `2`
- Iteration-cap check:
  - `sample_A`, first 20 spectra, `--max-nfev 300` produced the same selected-model agreement (`12/20`) as `--max-nfev 2000`.
  - observed least-squares `nfev` was already low (`mean ~22.6`, max `101`), so current parity differences are not caused by hitting the iteration cap.
- Current interpretation:
  - Speed improvement is robust: roughly `4x` to `14x` candidate-level speedup depending on model and dataset.
  - Parity is not yet acceptable for a default replacement because `peak_4 -> peak_5` selected-model transitions are common.
  - Many large RMSE deltas are least-squares improvements over lmfit, especially for weaker lower-peak models, so the decision point is not only numeric tolerance; the team needs to decide whether preserving legacy model choice or adopting better local optima is the priority.
  - Next tuning target: focus on model-selection stability between `peak_4_model` and `peak_5_model`, likely by comparing AIC/BIC penalty behavior, baseline lock behavior, and initial/bounds parity for the LA component.

## Execution Notes (2026-03-23)

- TASK-020 complete:
  - Added spectrum-level multiprocessing hook in fit stage:
    - `fitting/mos2_core/fitting/raman_lmfit.py`
    - new process-pool path with per-spectrum worker function
    - deterministic merge of per-spectrum results back to input order
  - Added runtime worker option to CLI entrypoints:
    - `fitting/mos2_raman/run_raw_pipeline.py` (`--workers`)
    - `fitting/mos2_pl/run_raw_pipeline.py` (`--workers`)
    - pipeline context now carries `fit_workers`
  - Added Run Analysis UI control and command wiring:
    - `gui/pages/1_Run_Analysis.py`
    - new `Fit workers (processes)` option passes `--workers`
  - Added multiprocessing safety + fallback behavior:
    - when `workers>1`, sets default process-safety env vars:
      - `OMP_NUM_THREADS=1`
      - `MKL_NUM_THREADS=1`
      - `OPENBLAS_NUM_THREADS=1`
    - if process-pool init fails in restricted environment, fit stage auto-falls back to sequential and logs reason.
  - Docs synced:
    - `README.md`
    - `AGENTS.md`
    - `ARCHITECTURE.md`
  - Validation:
    - `python -m py_compile` on updated fit/entrypoint modules: pass
    - Raman dummy pipeline: pass
    - PL dummy pipeline: pass
    - Raman raw smoke (`workers=1`, 2 spectra): pass
    - Raman raw smoke (`workers=2`): pass with automatic sequential fallback in restricted environment (`WinError 5`)
    - PL raw smoke (`workers=2`): pass with automatic sequential fallback in restricted environment (`WinError 5`)

## Execution Notes (2026-03-22)

- TASK-017 complete:
  - Standardized canonical packaging output contract:
    - distributable: `dist/mos2-analysis`
    - temporary build work: `dist/build`
  - Marked `build/`, `build_progressfix/`, `dist_progressfix/` as legacy fallback outputs (not default release targets).
  - Confirmed end-user distribution note is included via `PACKAGING_DIST_README.md` and documented in packaging docs/README/agent policy.
  - Build command now includes explicit post-build copy so distribution root contains:
    - `dist/mos2-analysis/PACKAGING_DIST_README.md`
- TASK-018 complete:
  - Updated Home page next-step order in `gui/Main.py` to `Run Analysis -> Flagged -> All Spectra -> Finalize`.
  - Swapped Streamlit page filenames so sidebar order is also aligned:
    - `gui/pages/2_Flagged_Spectra.py`
    - `gui/pages/3_All_Spectra_Viewer.py`
  - Synced docs to reflect flagged-first triage flow.
- TASK-019 complete:
  - Added canonical manual override module: `fitting/mos2_core/review/manual_overrides.py`.
  - Unified durable manual edits to one per-report file:
    - `data/results/{modality}/manual_refits/{run_id}_manual_overrides.json`
  - Added projection in common loader:
    - `gui/components/report_loader.py::load_report_payload()` now merges report JSON + override JSON.
  - Applied cross-page consistency by loading projected data through shared loader path (including `6_Sample_Comparison.py` cache-key fix with override mtime).
  - Added manual model override action in All Spectra:
    - `Apply Model Override` persists selected candidate into unified override JSON.
  - Stopped durable request/response/bundle persistence in All Spectra manual refit flow:
    - editor IPC files now run in temporary directory and are cleaned automatically.
  - Implemented report-linked bin behavior in Run Analysis/data bin:
    - selection list shows only report JSON + manual override JSON.
    - report JSON actions auto-link paired CSV + override JSON for move/restore/purge.

## Execution Notes (2026-03-20)

- TASK-001 complete:
  - Created `legacy/mos2_spectra_pipeline/` backup
  - Created `mos2_raman/` and copied full project contents
  - Updated module/document path references to `mos2_raman`
  - Verified smoke run: `python -m mos2_raman.src.core.run_dummy_pipeline`
- TASK-002 complete:
  - Added PL modality branch and PL fitter models (`pl_single_gaussian`, `pl_single_pvoigt`) in `src/fitting/raman_lmfit.py`
  - Expanded `config/pl.yaml` with PL fit parameters
  - Made `src/core/default_stages.py` config-aware for PL enablement
  - Verified synthetic PL run and report generation
- TASK-003 complete:
  - Updated `src/analysis/reporting.py` to output under `results/{modality}/reports`
  - Updated Streamlit report discovery to read new modality folders and legacy `results/reports`
  - Verified Raman + PL reports are produced in separated folders
- TASK-004 complete:
  - Updated `ARCHITECTURE.md` with modality branching, directory changes, and output path changes
- TASK-005 complete:
  - Added TASK-005 plan and executed Streamlit runtime verification
  - Verified local app response: `http://localhost:8501` returned HTTP `200`
  - Browser launch command for local URL succeeded under escalated permission (`browser_open=ok`)
  - No runtime/import errors observed in Streamlit startup logs
  - Note: browser process count telemetry in this environment remained `0`, so visual render confirmation is environment-limited
- TASK-006 complete:
  - Created new top-level structure: `fitting/`, `gui/`, `data/`
  - Added packages: `fitting/mos2_core`, `fitting/mos2_raman`, `fitting/mos2_pl`
  - Copied source/config/app/raw/results assets in non-destructive migration style
- TASK-007 complete:
  - Added new entrypoints:
    - `python -m fitting.mos2_raman.run_dummy_pipeline`
    - `python -m fitting.mos2_raman.run_raw_pipeline`
    - `python -m fitting.mos2_pl.run_dummy_pipeline`
    - `python -m fitting.mos2_pl.run_raw_pipeline`
  - Verified compile and smoke execution on new package paths
- TASK-008 complete:
  - Moved Streamlit runtime package to `gui/` and rewired imports (`gui.components.*`)
  - Updated report/config routing to:
    - results: `data/results/{raman,pl}/reports`
    - config: `fitting/mos2_raman/config`
  - Verified Streamlit launch from new root: `streamlit run gui/Main.py` (HTTP `200`)

## GUI UX Execution (2026-03-20)

- Applied (Good):
  - Global: 1, 2, 3, 5, 6
  - Main: 2, 3, 4, 5
  - Run analysis: 7, 8, 9
  - Flagged spectra: 11, 12
  - Map viewer: 15, 17 (shrink direction)
  - Model comparison: 19, 21
  - All spectra viewer: 23, 24, 25
  - Sample comparison: 27, 28, 29
  - Finalize: 31, 32, 33
- Implemented highlights:
  - Main entrypoint renamed to `gui/Main.py` and sidebar page order aligned so Finalize is last
  - Main page cards/labels simplified (`Active Artifacts`) and config snapshot moved to advanced expander
  - Run Analysis reorganized into step flow with live stage cards and generated artifact capture
  - Flagged Spectra includes top flag-reason summary and split layout for review vs manual decision
  - Map Viewer shows top state metrics and keeps `Map Summary` collapsed by default
  - Model Comparison supports sidebar `fit_status` filtering
  - All Spectra Viewer supports unified sidebar Y/X navigation with clearer index/coverage display
  - Sample Comparison sidebar reorganized into report/filter/display/advanced sections with coefficient help text
  - Finalize page adds checklist context and direct manifest download

## GUI UX Hold Backlog (2026-03-20)

- Global-4: Main `Map Summary` meaning tooltip/annotation redesign (hold)
- Global-7: Cross-page beginner/advanced mode split template (hold)
- Global-8: Global glossary/help for core terms (`fit_status`, `attention`, `invalid`, `map_summary`) (hold)
- Flagged-13: `mode_note` wording refinement to user-friendly text (hold)
- Map-16: Default color-scale strategy change to robust mode (hold)
- Model-20: Add single-line recommended model summary (hold)

## Data Path/Bin Update (2026-03-21)

- Flattened Raman raw path:
  - moved `data/raw/raman/Raman/*` -> `data/raw/raman/*`
  - removed now-empty `data/raw/raman/Raman`
- Added soft-delete Bin workflow in Run Analysis page:
  - move selected result files into `data/bin/results/{modality}`
  - restore selected Bin entries back to `data/results/{modality}`
  - permanently delete selected Bin entries from Bin with explicit confirmation
- Updated docs:
  - `README.md`, `ARCHITECTURE.md`, `AGENTS.md`

## Manual Refit Hybrid Workflow Update (2026-03-21)

- TASK-009 complete:
  - Added request/response contract module: `gui/components/manual_refit_contract.py`
  - Defined schema IDs:
    - `manual_refit_request.v1`
    - `manual_refit_response.v1`
  - Added peak extraction + response validation helpers
- TASK-010 complete:
  - Added desktop editor package files:
    - `gui/desktop_editor/app.py`
    - `gui/desktop_editor/main_window.py`
    - `gui/desktop_editor/plot_widget.py`
    - `gui/desktop_editor/peak_table.py`
    - `gui/desktop_editor/models.py`
    - `gui/desktop_editor/controller.py`
  - Supports one-spectrum interactive editing and JSON output save
- TASK-011 complete:
  - Replaced manual refit stub with reusable API:
    - `fitting/mos2_core/review/refit_api.py`
  - Added:
    - `ManualRefitRequest`
    - `SingleSpectrumRefitAPI`
    - `build_manual_refit_record`
  - Reuses existing lmfit engine path for one-spectrum refit
- TASK-012 complete:
  - Integrated All Spectra Viewer launcher flow:
    - writes editor request JSON
    - launches desktop editor subprocess
    - validates response
    - executes single-spectrum refit
    - renders manual before/after preview
  - File: `gui/pages/3_All_Spectra_Viewer.py`
- TASK-013 complete:
  - Added JSONL persistence store:
    - `fitting/mos2_core/review/manual_refit_store.py`
  - Appends manual refit records to:
    - `data/results/{modality}/manual_refits/manual_refits.jsonl`
  - Added per-session bundle snapshot `*_bundle.json`
  - Updated docs:
    - `README.md`, `ARCHITECTURE.md`, `AGENTS.md`, `requirements.txt`
- Additional stability fix:
  - Resolved `review` package circular import by making `default_stages` import review submodules directly

## All Spectra Sidebar Navigation Update (2026-03-21)

- Resolved index conflict between main-area row controls and sidebar spectrum index.
- Unified navigation in sidebar with coordinate axes:
  - `Row index (Y)` for vertical move (`Y1-X1 -> Y2-X1`)
  - `Spectrum index (X)` for horizontal move (`Y1-X1 -> Y1-X2`)
- Kept linear index fallback for reports without usable `map_x/map_y` or `Y#-X#` tokens.
- Validation:
  - AppTest smoke with single-row report (`Filtered Rows=1`): pass
  - AppTest smoke with grid report (`Y1-X1 -> Y2-X1 -> Y2-X2`): pass

## TASK-014/015 Execution Update (2026-03-21)

- TASK-014 complete:
  - Added graph style + smoothing config in `fitting/mos2_raman/config/raman_graph.yaml`:
    - shared colors (`raw/fit/baseline/components`)
    - smooth fit settings (`smooth_factor`, `max_points`)
    - desktop handle color settings
  - Updated `gui/components/spectrum_viewer.py`:
    - config-driven color/style rendering
    - denser fit plotting via interpolation/reconstruction on dense x-grid
    - baseline always overlaid in both main and manual preview graphs
  - Updated `gui/pages/3_All_Spectra_Viewer.py` to pass style/smoothing config to both graph renders.
- TASK-015 complete:
  - Reworked `gui/desktop_editor/plot_widget.py`:
    - mode switching (`Move`, `Zoom`, `Edit`)
    - draggable peak-top handle for center/height edits
    - draggable left/right half-maximum handles for FWHM edits
    - fixed-flag guardrails for center/height/FWHM edits
    - baseline + smoothed preview fit rendering with shared config colors
  - Updated `gui/desktop_editor/main_window.py`:
    - interaction mode selector UI
    - bidirectional sync between drag edits and peak table

## Run Analysis Option Update (2026-03-21)

- Added Run Analysis controls for Raman runtime tuning:
  - `peak_n_mode` (`auto`, `peak_2_model`, `peak_3_model`, `peak_4_model`, `peak_5_model`)
  - `distance_outlier` (`config`, `enabled`, `disabled`)
  - `delta_outlier` (`config`, `enabled`, `disabled`)
  - `si_calibration` (`config`, `enabled`, `disabled`)
- Wired UI -> CLI -> runtime config override path:
  - `gui/pages/1_Run_Analysis.py`
  - `fitting/mos2_raman/run_raw_pipeline.py`
  - `fitting/mos2_pl/run_raw_pipeline.py`
- Validation:
  - Raman single run with overrides applied in report config: pass
  - Raman batch run with overrides: pass
  - PL raw run with new options accepted: pass
  - Run Analysis page AppTest confirms 4 controls rendered: pass

## Run Analysis Live Status Update (2026-03-21)

- Updated Run Analysis live status logic to focus on fit-stage progress:
  - single mode: one `Fit Progress` card with `valid/attention/invalid`, `elapsed`, `eta`
  - batch mode: `Overall (fit only)` + `Current Fit`
- Batch overall now uses pre-counted total TXT files from selected run scope and pattern.
- Batch status now shows current batch/folder and estimated current file hint.
- Validation:
  - Run Analysis single AppTest smoke (`Run Analysis` click, pattern `Y1-X1.txt`): pass
  - Run Analysis batch AppTest smoke (`Run Analysis` click, batch parent + pattern `Y1-X1.txt`): pass
  - Existing pipeline/GUI/manual-refit smoke checks: pass

## Manual Refit UX Follow-up Update (2026-03-21)

- Extended TASK-014/015 manual editor behavior:
  - Desktop initial x-range now follows the same rule as All Spectra main graph:
    - `all_spectra_viewer.x_window` in `fitting/mos2_raman/config/raman_graph.yaml`
    - auto window from `e2g/a1g +/- peak_padding` with fallback range
  - Added `Autoscale (Main View)` in right-click menu (next to `View All` behavior)
  - Added Zoom mode double-click autoscale shortcut
  - Added live preview metric row in desktop editor:
    - `RMSE`, `AIC`, and delta vs before-fit values
  - Added `Auto Fit (Use Current as Initial)` button:
    - uses current edited peaks as initialization
    - runs one-spectrum auto-refit (`SingleSpectrumRefitAPI.submit_auto_refit`)
    - updates peak table/plot with returned fit parameters
- Related files:
  - `gui/components/graph_style.py`
  - `gui/desktop_editor/plot_widget.py`
  - `gui/desktop_editor/controller.py`
  - `gui/desktop_editor/main_window.py`
  - `fitting/mos2_core/review/refit_api.py`
  - `README.md`
  - `ARCHITECTURE.md`
- Validation:
  - `python -m py_compile` on updated modules: pass
  - Raman/PL dummy pipelines: pass
  - Raman raw single + batch smoke: pass
  - Streamlit HTTP smoke (`200`, port `8515`): pass
  - All Spectra Viewer single-row AppTest smoke: pass
  - Manual refit API smoke (`submit_refit` + `submit_auto_refit`): pass
  - Desktop editor offscreen smoke (autoscale/metric path): pass

## Manual Refit Handle Mapping Update (2026-03-21)

- Updated Edit mode interaction to split handle responsibilities:
  - left handle: `fraction` (`eta`)
  - top handle: `center` + `height`
  - right handle: `FWHM`
- Added `fraction` to editor request/response peak payload and editable peak table.
- Updated auto/manual refit API adapter to accept and apply per-peak `fraction` overrides.
- Related files:
  - `gui/components/manual_refit_contract.py`
  - `gui/desktop_editor/models.py`
  - `gui/desktop_editor/peak_table.py`
  - `gui/desktop_editor/plot_widget.py`
  - `gui/desktop_editor/controller.py`
  - `fitting/mos2_core/review/refit_api.py`
  - `fitting/mos2_raman/config/raman_graph.yaml`
  - `README.md`
  - `ARCHITECTURE.md`
  - `AGENTS.md`
- Validation:
  - `python -m py_compile` on updated manual-refit modules: pass
  - desktop handle-role smoke (`left=>fraction`, `top=>center/height`, `right=>FWHM`): pass
  - Raman dummy pipeline: pass
  - PL dummy pipeline: pass
  - Raman raw single run (`fraction_handle_single_smoke`): pass
  - Raman batch run (`--batch-subdirs`): pass
  - Streamlit HTTP smoke (`200`, port `8516`): pass
  - All Spectra single-row AppTest smoke (`Filtered Rows=1`): pass
  - Manual refit API smoke (`submit_refit` + `submit_auto_refit`): pass

## Manual Refit Math + Report Detail Update (2026-03-21)

- Manual editor + manual refit synthesis math was unified to lmfit-consistent area-normalized line-shape behavior.
  - Previous mismatch source:
    - editor preview/manual synthesis used `height`-mix approximation
    - pipeline fit metrics used lmfit `area/sigma/fraction` model math
  - Updated modules now use the consistent formulation:
    - `gui/desktop_editor/controller.py`
    - `gui/desktop_editor/plot_widget.py`
    - `fitting/mos2_core/review/refit_api.py`
- Report top-level `spectra[]` row export no longer uses summary-only key picking.
  - Selected fit `params` and `metrics` are copied through in detail.
  - Nested snapshots are also included as:
    - `fit_params`
    - `fit_metrics`
  - Updated module:
    - `fitting/mos2_core/analysis/reporting.py`
- Validation:
  - `python -m py_compile` on updated modules: pass
  - Raman raw single smoke (`top_level_detail_smoke`): pass
  - generated report row contains:
    - `line_profile`, `*_fraction`, `*_sigma`
    - `fit_params` / `fit_metrics`
  - desktop-editor start metric matches report metric on smoke sample (`RMSE`, `AIC` delta ~= numerical epsilon)

## Manual Refit UX Fixes Update (2026-03-22)

- Added fraction fixed-flag support across desktop/manual-refit flow.
  - New peak payload flag: `fixed_fraction`
  - Auto-refit honors fixed fraction (`lmfit fraction vary=False` when fixed)
  - Updated files:
    - `gui/desktop_editor/models.py`
    - `gui/desktop_editor/peak_table.py`
    - `gui/desktop_editor/plot_widget.py`
    - `gui/components/manual_refit_contract.py`
    - `fitting/mos2_core/review/refit_api.py`
- Fixed zoom reset bug when toggling fix flags in peak table.
  - Table edits now update peak state without full plot reinitialization/autoscale.
  - Updated files:
    - `gui/desktop_editor/main_window.py`
    - `gui/desktop_editor/plot_widget.py`
- Replaced mode combo with top icon toolbar for quicker `Move/Zoom/Edit` switching.
  - Updated file:
    - `gui/desktop_editor/main_window.py`
- Validation:
  - `python -m py_compile` on updated modules: pass
  - auto-refit fraction-fix smoke: pass (`fixed_fraction=True` preserved value exactly)
  - offscreen zoom-preservation smoke: pass (x-range unchanged across fix toggle)
  - offscreen icon-mode switch smoke: pass (`Move -> Zoom -> Edit`)

## Raman Anchor-Centered Fit Update (2026-03-22)

- Updated Raman n-peak center-coupling rule in anchor mode (`two_stage_anchor.enabled=true`):
  - removed legacy flat anchor-key fallback in config parsing/validation
  - anchor mode now uses anchor-centric offsets instead of prev->next chain for side peaks:
    - `LO = E2g - d_lo_from_e2g` (`d_lo_from_e2g` init from `abs(lo_offset_from_e2g)`, bounds `[0.5, 10.0]`)
    - `ZO = A1g + d_zo_from_a1g`
    - `LA = A1g + d_la_from_a1g`
  - `E2g/A1g` remain direct parameters under anchor window bounds (`anchor +/- window`)
- Related files:
  - `fitting/mos2_core/fitting/raman_lmfit.py`
  - `fitting/mos2_core/io/config_loader.py`
  - `fitting/mos2_raman/config/raman.yaml`
  - `fitting/mos2_pl/config/raman.yaml`
  - `ARCHITECTURE.md`
- Validation:
  - `python -m py_compile` on updated fitting/config-loader modules: pass
  - `python -m fitting.mos2_raman.run_dummy_pipeline`: pass
  - `python -m fitting.mos2_pl.run_dummy_pipeline`: pass
  - `python -m fitting.mos2_raman.run_raw_pipeline --raw-dir data/raw/raman/sample_A --pattern Y1-X1.txt --run-id anchor_centered_smoke`: pass

## Raman Config Layout Sync Update (2026-03-22)

- Reordered `fit` sections for readability and maintenance consistency:
  - `fitting/mos2_raman/config/raman.yaml`
  - `fitting/mos2_pl/config/raman.yaml`
- Both files now follow the same 7-block execution-order layout:
  1. ROI/comparison windows
  2. ordering/anchor policy
  3. anchor seeds/relative offsets
  4. center bounds
  5. width bounds
  6. model priors
  7. prefit gate
- Synced docs:
  - `README.md`
  - `AGENTS.md`
  - `ARCHITECTURE.md`
- Validation:
  - config load smoke (`load_pipeline_config`) for Raman config: pass

## Raman Auto-Refine (RMSE>=1%) Update (2026-03-22)

- Added optional second-pass Raman refinement in fit stage (`y_corr` objective).
  - Config path: `fit.auto_refine`
    - `enabled: true`
    - `min_rmse_improvement: 0.01`
  - Scope: Raman n-peak models (`peak_2_model`~`peak_5_model`)
  - Adoption rule: replace first-pass candidate only if
    - `(rmse_before - rmse_after) / rmse_before >= min_rmse_improvement`
- Refine implementation uses current candidate params as initialization and reruns fit with relaxed independent centers.
- Related files:
  - `fitting/mos2_core/fitting/raman_lmfit.py`
  - `fitting/mos2_core/io/config_loader.py`
  - `fitting/mos2_raman/config/raman.yaml`
  - `fitting/mos2_pl/config/raman.yaml`
  - `README.md`
  - `ARCHITECTURE.md`
  - `AGENTS.md`
- Validation:
  - `python -m py_compile` on updated fitting/config modules: pass
  - Raman/PL config load smoke: pass
  - Raman dummy pipeline: pass
  - PL dummy pipeline: pass
  - Raman raw single smoke (`--pattern Y1-X1.txt`): pass

## Constraint-vs-NFEV Investigation Plan (2026-03-22)

- Goal:
  - quantify which fitting constraints reduce/increase `nfev`
  - identify constraints that trade speed vs fit-quality most strongly
- Scope (Phase 1):
  - Raman n-peak first-pass fitting (`peak_2`~`peak_5`) on `y_corr`
  - one-by-one constraint ablation for:
    - `enforce_peak_order` on/off
    - `two_stage_anchor.enabled` on/off
  - settings matrix:
    1. `order_on + anchor_on` (current baseline)
    2. `order_off + anchor_on`
    3. `order_on + anchor_off`
    4. `order_off + anchor_off`
- Metrics:
  - per-model `nfev`
  - spectrum-level total `nfev` across candidate models
  - paired `rmse` movement for context (speed-only interpretation 諛⑹?)
- Output artifacts:
  - ablation summary table (mean/median nfev by setting)
  - raw detail CSV for reproducible follow-up
- Status:
  - Phase 1 Done (order/anchor ablation)
  - Phase 2 Pending (additional constraints)

### Phase 1 Results (9 spectra, `sample_B`, first-pass n-peak fits)

- Output CSV:
  - `data/results/raman/reports/constraint_ablation_20260322.csv`
- Aggregate totals (spectrum-level sum of candidate-model `nfev`):
  - `order_on + anchor_on`:
    - mean total `nfev`: `1131.78`
    - median total `nfev`: `951.0`
    - mean model-avg RMSE: `9.119107`
  - `order_off + anchor_on`:
    - mean total `nfev`: `2226.33`
    - median total `nfev`: `1046.0`
    - mean model-avg RMSE: `8.793191`
  - `order_on + anchor_off`:
    - mean total `nfev`: `5945.22`
    - median total `nfev`: `3072.0`
    - mean model-avg RMSE: `8.782082`
  - `order_off + anchor_off`:
    - mean total `nfev`: `6774.56`
    - median total `nfev`: `1581.0`
    - mean model-avg RMSE: `9.426566`
- Model-level `nfev` observations:
  - `anchor_on` has the strongest `nfev` suppression effect overall.
  - `anchor_off` inflates `peak_4/peak_5` most sharply.
  - `order_on + anchor_on` gives lowest average `nfev`; `peak_5` mean `nfev` dropped to `138.2` in this sample set.
- Interpretation note:
  - Disabling constraints can improve average RMSE on some subsets, but often at major `nfev` cost and with high variance.

### Phase 1 Results (81 spectra full set, `sample_B`)

- Output CSV:
  - `data/results/raman/reports/constraint_ablation_81_20260322.csv`
- Integrity check:
  - files processed: `81`
  - setting-level rows: `324` (`81 x 4`)
  - model rows: `1620` (`81 x 4 x 5`)
- Aggregate totals (spectrum-level sum of candidate-model `nfev`):
  - `order_on + anchor_on`:
    - mean total `nfev`: `3303.79`
    - median total `nfev`: `1642.0`
    - mean best RMSE: `4.502232`
  - `order_off + anchor_on`:
    - mean total `nfev`: `2929.91`
    - median total `nfev`: `1421.0`
    - mean best RMSE: `4.558623`
  - `order_on + anchor_off`:
    - mean total `nfev`: `8213.33`
    - median total `nfev`: `3404.0`
    - mean best RMSE: `4.523653`
  - `order_off + anchor_off`:
    - mean total `nfev`: `4899.74`
    - median total `nfev`: `1406.0`
    - mean best RMSE: `4.597658`
- Core findings:
  - `anchor_off` is the largest source of `nfev` increase, especially with `order_on` (`+4909.54` mean total `nfev` vs `anchor_on`).
  - largest per-model inflation under `anchor_off` appears in `peak_5`:
    - `order_on`: `1647.9 -> 4256.7`
    - `order_off`: `1771.7 -> 3377.9`
  - RMSE difference is mixed by spectrum; speed impact is much larger and more consistent than quality gain.

## First-Pass vs Auto-Refine NFEV Snapshot (2026-03-22)

- Goal:
  - compare runtime cost (`nfev`) between first-pass candidates and auto-refine outputs on the same 81-spectra set.
- Input reports:
  - `data/results/raman/reports/sample_H_fit_report.json` (first-pass baseline)
  - `data/results/raman/reports/sample_H_auto_fit_fit_report.json` (auto-refine enabled run)
- Matched comparison artifact:
  - `data/results/raman/reports/first_vs_refine_nfev_from_reports_81_20260322.csv`
- Coverage:
  - `81 spectra x 4 candidate models = 324` matched candidate pairs
- Aggregate summary:
  - candidate-level mean:
    - `first_nfev = 300.5`
    - `auto_nfev = 19,457.1`
    - delta `+19,156.6`
  - spectrum-level total mean:
    - `first_total_nfev = 1,202.1`
    - `auto_total_nfev = 77,828.4`
    - median ratio `~81.9x`
- Apply-rate context:
  - auto-refine applied (`rmse improvement >= 1%`): `264 / 324` (`81.5%`)
  - not applied: `60 / 324` (same nfev as first-pass for those rows)
- Model-level nfev delta (auto - first):
  - `peak_2_model`: `-34.1` (slightly lower)
  - `peak_3_model`: `+25,863.6`
  - `peak_4_model`: `+37,512.2`
  - `peak_5_model`: `+13,284.7`
- Note for follow-up:
  - time increase is dominated by refine `peak_3/4/5`; next step is targeted constraint tuning for refine stage only.

## Run Analysis Si Calibration Toggle Update (2026-03-22)

- Added runtime on/off override for Si calibration offset in Run Analysis.
  - UI control: `si_calibration` (`config|enabled|disabled`)
  - CLI option: `--si-calibration {config,enabled,disabled}`
- Wired path:
  - `gui/pages/1_Run_Analysis.py`
  - `fitting/mos2_raman/run_raw_pipeline.py`
  - `fitting/mos2_pl/run_raw_pipeline.py`
- Behavior:
  - `config`: keep `raman.yaml` value (`si_calibration.enabled`)
  - `enabled|disabled`: force runtime override of `raman.si_calibration.enabled`
- Docs synced:
  - `README.md`
  - `ARCHITECTURE.md`
  - `AGENTS.md`

## Git Workflow Policy Update (2026-03-22)

- User preference applied:
  - Codex should proactively use `branch + commit` workflow by default.
- Policy added to `AGENTS.md`:
  - create task-scoped branch before edits
  - commit completed changes with scoped message
  - keep behavior-changing code/doc updates in same commit
  - respect explicit user override when no-commit/no-branch is requested


## Raman Mapping CSV Splitter (2026-10-29)

- Added `fitting/mos2_raman/split_mapping_csv.py` (`python -m fitting.mos2_raman.split_mapping_csv <map.CSV>`).
- Purpose: convert mapping CSV exports (`FILETYPE=RAMAN SPECTRUM (MAPPING)`, one spectrum per row) into per-point `Y###-X###.txt` folders that the existing raw loader and `run_raw_pipeline` consume.
- Standalone pre-processing tool only; pipeline/GUI behavior unchanged.
- First use: `data/raw/raman/sample_I` (Before/After CSV pair). The After CSV is an incomplete scan (17180/18632 points; one truncated row skipped).
- Tests: `tests/test_split_mapping_csv.py`.
- Docs synced:
  - `README.md`
  - `ARCHITECTURE.md`
  - `AGENTS.md`

## Packaging Pre-Build Fixes (2026-10-29)

- Scope: prepare the PyInstaller package for a rebuild (no build run in this task).
- Removed legacy leftovers `build/`, `build_progressfix/`, `dist_progressfix/`, and `dist/build` (user request).
- Frozen config path fix:
  - added `runtime_resource_root()` / `raman_config_dir()` to `fitting/mos2_core/core/runtime_paths.py`
  - `SingleSpectrumRefitAPI`, `gui/components/graph_style.py`, `gui/components/report_loader.py`, and the desktop editor controller read config from the bundle (`_internal`) when frozen
  - before: All Spectra manual refit used `<exe folder>/fitting/mos2_raman/config` and failed in the exe
- Frozen multiprocessing fix:
  - `packaging/entry_run_raman.py` / `entry_run_pl.py` call `multiprocessing.freeze_support()`
  - `raman_lmfit` re-raises `BrokenExecutor` so a dead pool falls back to sequential instead of marking every pending spectrum `invalid`
- `PACKAGING_DIST_README.md`: end-user `data\raw\raman` / `data\raw\pl` folder setup and `--workers` usage.
- Tests: `tests/test_packaging_runtime.py` (frozen path simulation, broken-pool fallback).
- Validation (source mode): Raman/PL dummy, Raman single + batch, GUI HTTP 200, All Spectra single-row AppTest, refit API smoke (source + simulated frozen layout), `packaging/entry_run_raman.py --workers 4` on 81 spectra (no fallback, 81 valid).
- Still required after the next build: run the exe checks listed in `PACKAGING_PYINSTALLER.md` (frozen `--workers 4`, All Spectra manual refit).
- Found during exe verification: desktop editor crashed on open (`NameError: snapshot_modality` in `plot_widget._resolve_main_x_range`, regression from `6bdec33`; source runs too). Fixed by resolving modality locally; regression test `tests/test_desktop_editor_plot.py`.
- Ship input folders: `mos2_optical_analysis.spec` now creates `dist/mos2-analysis/data/raw/{raman,pl}` (with a `.md` placeholder) so the dist folder can be handed over without setup; `PACKAGING_DIST_README.md` updated.

## Thresholds File (2026-10-30)

- Scope: collect user-tunable judgement thresholds into one external file for packaged-app users.
- New root `thresholds.yaml`, deep-merged over `fitting/{mos2_raman,mos2_pl}/config/*.yaml` by `load_pipeline_config` (path via `runtime_paths.thresholds_path()`).
- Moved out of section YAMLs: `raman.fit.prefit` (`enabled`, SNR mins), `raman.si_calibration` (`min_points`, `max_abs_offset`), `raman.post_selection_qc`, `pl.despike.threshold`, `review.confidence_threshold`, `raman_graph.flagged_spectra.legacy_thresholds`.
- Previously hardcoded, now configurable with identical defaults: `{raman,pl}.quality_flags` (`analysis/reporting.py`), `pl.fit.spike_check` (`raman_lmfit`).
- Packaging: spec bundles `thresholds.yaml` into `_internal` (fallback) and copies it next to the exe.
- Tests: `tests/test_thresholds_config.py` (merge, override, typo/missing-key errors, frozen path order, `r2_min` reaching the report).
- Validation: merged config diff vs pre-change = only the new keys; Raman/PL dummy, Raman single + batch, PL single (real data), GUI HTTP 200, All Spectra single-row AppTest, auto refit API smoke: pass. 17 tests pass.
- Not covered by `confidence.py` `high_rmse` (0.2): label-only, does not change status; left hardcoded.
