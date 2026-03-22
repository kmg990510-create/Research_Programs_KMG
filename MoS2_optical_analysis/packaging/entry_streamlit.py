"""PyInstaller launcher for the Streamlit app."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _resolve_main_script() -> Path:
    candidates: list[Path] = []

    exe_dir = Path(sys.executable).resolve().parent
    candidates.append(exe_dir / "gui" / "Main.py")

    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(Path(meipass) / "gui" / "Main.py")

    candidates.append(Path(__file__).resolve().parents[1] / "gui" / "Main.py")

    for path in candidates:
        if path.exists():
            return path.resolve()

    checked = "\n".join(str(path) for path in candidates)
    raise FileNotFoundError(f"Could not locate gui/Main.py. Checked:\n{checked}")


def _with_default_streamlit_args(user_args: list[str]) -> list[str]:
    # Packaged app must run with production frontend assets, not dev-server mode.
    has_dev_mode = any(
        arg == "--global.developmentMode" or arg.startswith("--global.developmentMode=")
        for arg in user_args
    )
    if has_dev_mode:
        return user_args
    return [*user_args, "--global.developmentMode", "false"]


def main() -> int:
    main_script = _resolve_main_script()
    bundled_code_root = main_script.parents[1]
    project_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else bundled_code_root

    if str(bundled_code_root) not in sys.path:
        sys.path.insert(0, str(bundled_code_root))
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    os.chdir(project_root)

    from streamlit.web import cli as stcli

    user_args = _with_default_streamlit_args(list(sys.argv[1:]))
    sys.argv = ["streamlit", "run", str(main_script), *user_args]
    return int(stcli.main())


if __name__ == "__main__":
    raise SystemExit(main())
