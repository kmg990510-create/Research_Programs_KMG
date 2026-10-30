from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from fitting.mos2_core.core import build_info

WORKSPACE = Path(__file__).resolve().parents[1]


def test_collect_reads_workspace_git_commit() -> None:
    info = build_info.collect_git_build_info(WORKSPACE)
    assert len(info["commit"]) == 40
    assert info["commit_short"] == info["commit"][:7]
    assert info["commit_date"] and info["built_at"]


def test_collect_outside_git_falls_back_to_unknown(tmp_path: Path) -> None:
    info = build_info.collect_git_build_info(tmp_path)
    assert info["commit_short"] == "unknown"
    assert "commit unknown" in build_info.format_build_label(info)


def test_frozen_run_shows_bundled_build_info(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bundle_dir = tmp_path / "mos2-analysis" / "_internal"
    bundle_dir.mkdir(parents=True)
    payload = {
        "commit": "eec2d44e31c1399ae7cd8167688c384fe25699e9",
        "commit_short": "eec2d44",
        "commit_date": "2026-10-30T17:31:35+09:00",
        "dirty": False,
        "built_at": "2026-10-30T09:00:00+00:00",
    }
    (bundle_dir / build_info.BUILD_INFO_FILENAME).write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_dir), raising=False)

    label = build_info.format_build_label(build_info.load_build_info())
    # UTC build time is shown in KST.
    assert label == "Build | commit eec2d44 | committed 2026-10-30 17:31 KST | built 2026-10-30 18:00 KST"
    assert "eec2d44e31c1399ae7cd8167688c384fe25699e9" in build_info.format_build_text(payload)


def test_source_run_label_has_no_build_time() -> None:
    label = build_info.format_build_label(build_info.load_build_info())
    assert label.startswith("Source run | commit ")
    assert "built" not in label
