"""GUI package for Streamlit app."""

import sys as _sys
from pathlib import Path as _Path

# ``labkit`` (shared lab code) sits next to this program in the repository. In the
# Docker image and the exe it is placed inside the program folder / bundle instead.
_PROGRAM_ROOT = _Path(__file__).resolve().parents[1]
if not (_PROGRAM_ROOT / "labkit").is_dir() and (_PROGRAM_ROOT.parent / "labkit").is_dir():
    if str(_PROGRAM_ROOT.parent) not in _sys.path:
        _sys.path.append(str(_PROGRAM_ROOT.parent))
