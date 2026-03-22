# -*- mode: python ; coding: utf-8 -*-

"""
PyInstaller spec for the mixed MoS2 optical analysis project.

This build intentionally creates multiple executables:
- `mos2-analysis.exe`: Streamlit launcher (top-level UI)
- `mos2-run-raman.exe`: Raman raw pipeline runner (used by Run Analysis page)
- `mos2-run-pl.exe`: PL raw pipeline runner (used by Run Analysis page)
- `mos2-desktop-editor.exe`: PySide6 manual refit editor (used by All Spectra page)

Using separate targets keeps subprocess flows working in frozen mode.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata


PROJECT_ROOT = Path(SPECPATH).resolve()


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

# Streamlit multipage needs real `gui/Main.py` and `gui/pages/*.py` files at runtime.
datas += _safe_collect_data_files("gui", include_py_files=True)

# YAML runtime configs are file-based and must be bundled for frozen execution.
datas += _safe_collect_data_files("fitting.mos2_raman", includes=["config/*.yaml"])
datas += _safe_collect_data_files("fitting.mos2_pl", includes=["config/*.yaml"])

# Streamlit and visualization packages often read package metadata at runtime.
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

# Include project packages used both by Streamlit pages and worker executables.
hiddenimports += _safe_collect_submodules("fitting")
hiddenimports += _safe_collect_submodules("gui")

# Streamlit relies on dynamic imports; collecting submodules prevents missing-module errors.
hiddenimports += _safe_collect_submodules("streamlit")

# pyqtgraph uses dynamic imports depending on backend/features.
hiddenimports += _safe_collect_submodules("pyqtgraph")

# Explicitly include modules used by launcher/runtime indirection.
hiddenimports += [
    "streamlit.web.cli",
    "streamlit.web.bootstrap",
    "PySide6.QtSvg",
    "PySide6.QtOpenGLWidgets",
]

hiddenimports = sorted(set(hiddenimports))


scripts = [
    str(PROJECT_ROOT / "packaging" / "entry_streamlit.py"),
    str(PROJECT_ROOT / "packaging" / "entry_run_raman.py"),
    str(PROJECT_ROOT / "packaging" / "entry_run_pl.py"),
    str(PROJECT_ROOT / "packaging" / "entry_desktop_editor.py"),
]


a = Analysis(
    scripts=scripts,
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Not needed in packaged app/runtime flow.
        "legacy",
        "pytest",
        "tkinter",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)


exe_main = EXE(
    pyz,
    a.scripts[0],
    [],
    exclude_binaries=True,
    name="mos2-analysis",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

exe_raman = EXE(
    pyz,
    a.scripts[1],
    [],
    exclude_binaries=True,
    name="mos2-run-raman",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

exe_pl = EXE(
    pyz,
    a.scripts[2],
    [],
    exclude_binaries=True,
    name="mos2-run-pl",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

exe_editor = EXE(
    pyz,
    a.scripts[3],
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
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="mos2-analysis",
)
