"""Build identification (git commit + dates) for packaged and source runs.

Stdlib only: the PyInstaller spec loads this file directly to write `build_info.json`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BUILD_INFO_FILENAME = "build_info.json"
BUILD_INFO_TEXT_FILENAME = "BUILD_INFO.txt"

# Dates are shown in Korea time; GitHub Actions runners build in UTC.
DISPLAY_TZ = timezone(timedelta(hours=9), "KST")


def _git(repo_dir: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_dir), *args],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def collect_git_build_info(repo_dir: Path) -> dict:
    """Commit hash/date of `repo_dir` plus the current time as the build time."""
    commit = _git(repo_dir, "rev-parse", "HEAD")
    return {
        "commit": commit or "unknown",
        "commit_short": commit[:7] if commit else "unknown",
        "commit_date": _git(repo_dir, "log", "-1", "--format=%cI") or None,
        # Tracked files edited but not committed: the build is not exactly that commit.
        "dirty": bool(_git(repo_dir, "status", "--porcelain", "--untracked-files=no")),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def load_build_info() -> dict:
    """
    Frozen run: the `build_info.json` the spec bundled in `_internal`.
    Source run: live git info of the workspace (`source: true`, no build time).
    """
    from fitting.mos2_core.core.runtime_paths import runtime_resource_root

    root = runtime_resource_root()
    if getattr(sys, "frozen", False):
        try:
            return json.loads((root / BUILD_INFO_FILENAME).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"commit_short": "unknown"}
    info = collect_git_build_info(root)
    info["source"] = True
    info.pop("built_at", None)
    return info


def _display_date(value: str | None) -> str:
    if not value:
        return "unknown"
    try:
        return datetime.fromisoformat(value).astimezone(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M KST")
    except ValueError:
        return value


def format_build_label(info: dict) -> str:
    commit = str(info.get("commit_short") or "unknown")
    if info.get("dirty"):
        commit += " (+uncommitted changes)"
    parts = [f"commit {commit}", f"committed {_display_date(info.get('commit_date'))}"]
    if info.get("source"):
        return "Source run | " + " | ".join(parts)
    parts.append(f"built {_display_date(info.get('built_at'))}")
    return "Build | " + " | ".join(parts)


def format_build_text(info: dict) -> str:
    """Contents of `BUILD_INFO.txt` next to the exe."""
    return (
        "MoS2 optical analysis build\n"
        f"commit:    {info.get('commit', 'unknown')}{' (+uncommitted changes)' if info.get('dirty') else ''}\n"
        f"committed: {_display_date(info.get('commit_date'))}\n"
        f"built:     {_display_date(info.get('built_at'))}\n"
    )
