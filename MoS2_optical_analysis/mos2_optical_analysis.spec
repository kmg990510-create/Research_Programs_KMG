# -*- mode: python ; coding: utf-8 -*-

"""
PyInstaller spec for the mixed MoS2 optical analysis project.

This build creates multiple executables:
- `mos2-analysis.exe`: Streamlit launcher (top-level UI)
- `mos2-run-raman.exe`: Raman raw pipeline runner (Run Analysis worker)
- `mos2-run-pl.exe`: PL raw pipeline runner (Run Analysis worker)
- `mos2-desktop-editor.exe`: PySide6 manual refit editor worker
"""

import shutil
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata


PROJECT_ROOT = Path(SPECPATH).resolve()
DIST_README = PROJECT_ROOT / "PACKAGING_DIST_README.md"
THRESHOLDS = PROJECT_ROOT / "thresholds.yaml"


def _safe_collect_data_files(package: str, **kwargs):
    try:
        return collect_data_files(package, **kwargs)
    except Exception:
        return []


def _safe_collect_submodules(package: str):
    try:
        return collect_submodules(package)
    except Exception:
        return []


def _safe_copy_metadata(package: str):
    try:
        return copy_metadata(package)
    except Exception:
        return []


datas = []

# Streamlit multipage needs real app/page .py files bundled as data.
datas += _safe_collect_data_files("gui", include_py_files=True)

# Streamlit frontend/static assets (index.html, JS/CSS bundles, templates).
datas += _safe_collect_data_files("streamlit")

# Runtime YAML config files.
datas += _safe_collect_data_files("fitting.mos2_raman", includes=["config/*.yaml"])
datas += _safe_collect_data_files("fitting.mos2_pl", includes=["config/*.yaml"])

# Default thresholds bundled in `_internal` as the fallback when the user removes
# the editable copy next to the exe (see runtime_paths.thresholds_path()).
datas.append((str(THRESHOLDS), "."))

# Minimal user-facing usage note shipped in distribution root.
if DIST_README.exists():
    datas.append((str(DIST_README), "."))

# Keep package metadata for runtime version/plugin checks.
for package_name in (
    "streamlit",
    "plotly",
    "pydeck",
    "altair",
    "watchdog",
    "tornado",
    "protobuf",
    "lmfit",
    "numpy",
    "scipy",
    "pandas",
    "PyYAML",
    "pyqtgraph",
    "PySide6",
):
    datas += _safe_copy_metadata(package_name)


hiddenimports = []
hiddenimports += _safe_collect_submodules("fitting")
hiddenimports += _safe_collect_submodules("gui")
hiddenimports += _safe_collect_submodules("streamlit")
hiddenimports += _safe_collect_submodules("pyqtgraph")
hiddenimports += [
    "streamlit.web.cli",
    "streamlit.web.bootstrap",
    "PySide6.QtSvg",
    "PySide6.QtOpenGLWidgets",
]
hiddenimports = sorted(set(hiddenimports))


COMMON_ANALYSIS_KWARGS = dict(
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "legacy",
        "pytest",
        "tkinter",
    ],
    noarchive=False,
    optimize=0,
)


a_main = Analysis(
    [str(PROJECT_ROOT / "packaging" / "entry_streamlit.py")],
    **COMMON_ANALYSIS_KWARGS,
)
pyz_main = PYZ(a_main.pure)
exe_main = EXE(
    pyz_main,
    a_main.scripts,
    [],
    exclude_binaries=True,
    name="mos2-analysis",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)


a_raman = Analysis(
    [str(PROJECT_ROOT / "packaging" / "entry_run_raman.py")],
    **COMMON_ANALYSIS_KWARGS,
)
pyz_raman = PYZ(a_raman.pure)
exe_raman = EXE(
    pyz_raman,
    a_raman.scripts,
    [],
    exclude_binaries=True,
    name="mos2-run-raman",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)


a_pl = Analysis(
    [str(PROJECT_ROOT / "packaging" / "entry_run_pl.py")],
    **COMMON_ANALYSIS_KWARGS,
)
pyz_pl = PYZ(a_pl.pure)
exe_pl = EXE(
    pyz_pl,
    a_pl.scripts,
    [],
    exclude_binaries=True,
    name="mos2-run-pl",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)


a_editor = Analysis(
    [str(PROJECT_ROOT / "packaging" / "entry_desktop_editor.py")],
    **COMMON_ANALYSIS_KWARGS,
)
pyz_editor = PYZ(a_editor.pure)
exe_editor = EXE(
    pyz_editor,
    a_editor.scripts,
    [],
    exclude_binaries=True,
    name="mos2-desktop-editor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)


coll = COLLECT(
    exe_main,
    exe_raman,
    exe_pl,
    exe_editor,
    a_main.binaries,
    a_main.datas,
    a_raman.binaries,
    a_raman.datas,
    a_pl.binaries,
    a_pl.datas,
    a_editor.binaries,
    a_editor.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="mos2-analysis",
)


# Ship empty input folders so the dist folder can be handed over as-is.
# A placeholder file keeps them alive through zip/copy; `.md` is never matched
# by the Raman (`*.txt`) or PL (`*.asc`) spectrum patterns.
RAW_PLACEHOLDER = (
    "Put one folder per sample here (e.g. SampleA/Y001-X001.txt ...).\n"
    "See PACKAGING_DIST_README.md in the app folder.\n"
)
for modality in ("raman", "pl"):
    raw_dir = Path(DISTPATH) / "mos2-analysis" / "data" / "raw" / modality
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "_PUT_SAMPLE_FOLDERS_HERE.md").write_text(RAW_PLACEHOLDER, encoding="utf-8")

# User-editable thresholds next to the exe (read before the bundled copy).
shutil.copy2(THRESHOLDS, Path(DISTPATH) / "mos2-analysis" / THRESHOLDS.name)
