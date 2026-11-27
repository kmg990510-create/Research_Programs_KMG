"""Check repository hygiene rules so private data, binaries, and versioned files never enter git."""

from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]

ALLOWED_BINARIES: frozenset[str] = frozenset(
    {
        "FET_analysis/docs/FET_분석_원리.pptx",
        "MoS2_adsorption_sim/docs/MoS2_흡착_시뮬레이션_원리.pptx",
        "MoS2_optical_analysis/docs/MoS2_분석_원리.pptx",
        "MoS2_optical_analysis/docs/MoS2_Raman PL_분석_사용_매뉴얼.pptx",
    }
)

FORBIDDEN_EXTS: frozenset[str] = frozenset(
    {".pptx", ".pdf", ".png", ".jpg", ".jpeg", ".npy", ".npz", ".csv", ".xyz", ".traj", ".extxyz"}
)

_RE_DATA_DIR = re.compile(r"(^|/)data/")
_RE_RESEARCH_OUT = re.compile(r"(^|/)research/[^/]+/(logs|figures|reports|scratch|slides/templates)/")
_RE_DOCS_FIGURES = re.compile(r"(^|/)docs/figures/")
_RE_PRIVATE_DOC = re.compile(r"(^PLANS\.md$|Master_Report|internal seminar)", re.IGNORECASE)
_RE_VERSIONED_STEM = re.compile(r"(_v\d+|_updated|_final|_review)$", re.IGNORECASE)
_RE_RESULT_BUILDER = re.compile(r"^build_.*(pptx|deck|report|slides).*\.py$", re.IGNORECASE)

PRE_COMMIT_HOOK = """#!/usr/bin/env sh
if command -v python >/dev/null 2>&1; then
  exec python scripts/check_repo_hygiene.py --staged
elif command -v python3 >/dev/null 2>&1; then
  exec python3 scripts/check_repo_hygiene.py --staged
elif command -v py >/dev/null 2>&1; then
  exec py -3 scripts/check_repo_hygiene.py --staged
fi
echo "check_repo_hygiene: Python interpreter not found in PATH" >&2
exit 1
"""


def check_paths(paths: Iterable[str]) -> list[str]:
    """Return human-readable violation strings for any disallowed repository paths."""
    violations: list[str] = []
    for raw in paths:
        norm = raw.strip().replace("\\", "/")
        if not norm:
            continue
        p = PurePosixPath(norm)
        base = p.name
        stem = p.stem
        ext = p.suffix.lower()

        if _RE_DATA_DIR.search(norm):
            violations.append(f"{norm}: Private data directory must never be tracked")
        if _RE_RESEARCH_OUT.search(norm):
            violations.append(f"{norm}: Research outputs/logs/figures/reports/scratch/templates stay local")
        if _RE_DOCS_FIGURES.search(norm):
            violations.append(f"{norm}: docs/figures/ is reserved for private local data/figures/")
        if _RE_PRIVATE_DOC.search(base):
            violations.append(f"{norm}: Private report/plan filename is disallowed in tracked files")
        if ext in FORBIDDEN_EXTS and norm not in ALLOWED_BINARIES:
            violations.append(f"{norm}: Binary/data extension {ext!r} is disallowed outside explicit allowlist")
        if _RE_VERSIONED_STEM.search(stem):
            violations.append(f"{norm}: Versioned filename suffix (_vN/_updated/_final/_review) is disallowed")
        if _RE_RESULT_BUILDER.match(base):
            violations.append(f"{norm}: Move result-hardcoded report/deck builders to data/.../reports/")
    return violations


def _git_paths(staged: bool) -> list[str]:
    if staged:
        cmd = ["git", "-c", "core.quotepath=false", "diff", "--cached", "--name-only", "--diff-filter=ACMR"]
    else:
        cmd = ["git", "-c", "core.quotepath=false", "ls-files"]
    out = subprocess.check_output(cmd, cwd=REPO_ROOT, text=True, encoding="utf-8")
    return [line for line in out.splitlines() if line.strip()]


def _install_hook() -> Path:
    hook_path = REPO_ROOT / ".git" / "hooks" / "pre-commit"
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    hook_path.write_text(PRE_COMMIT_HOOK, encoding="utf-8", newline="\n")
    try:
        os.chmod(hook_path, 0o755)
    except OSError:
        pass
    return hook_path


def _run_self_test() -> None:
    bad_cases = [
        ("MoS2_adsorption_sim/data/4-ATP.xyz", "Private data directory"),
        ("data/results/out.txt", "Private data directory"),
        ("MoS2_optical_analysis/research/atp_raman/logs/01.txt", "Research outputs"),
        ("MoS2_optical_analysis/research/atp_raman/scratch/tmp.py", "Research outputs"),
        ("MoS2_optical_analysis/research/atp_raman/slides/templates/base.pptx", "Research outputs"),
        ("MoS2_adsorption_sim/docs/figures/summary.png", "docs/figures/"),
        ("MoS2_adsorption_sim/PLANS.md", "Private report/plan filename"),
        ("MoS2_adsorption_sim/docs/MoS2_4ATP_Master_Report_v6.md", "Private report/plan filename"),
        ("MoS2_adsorption_sim/docs/20261111 internal seminar 최종.pdf", "Private report/plan filename"),
        ("MoS2_optical_analysis/report.csv", "Binary/data extension"),
        ("MoS2_adsorption_sim/docs/design_v2.md", "Versioned filename suffix"),
        ("MoS2_adsorption_sim/docs/notes_final.md", "Versioned filename suffix"),
        ("MoS2_adsorption_sim/scripts/build_5slide_overview_pptx.py", "report/deck builders"),
        ("MoS2_optical_analysis/research/atp_raman/slides/build_deck.py", "report/deck builders"),
    ]
    for path, expected_frag in bad_cases:
        hits = check_paths([path])
        assert any(expected_frag in h for h in hits), f"Expected {expected_frag!r} for {path}, got {hits}"

    good_cases = [
        "AGENTS.md",
        "scripts/check_repo_hygiene.py",
        "MoS2_adsorption_sim/docs/PLAN.md",
        "MoS2_adsorption_sim/docs/DEV_LOG.md",
        "MoS2_adsorption_sim/configs/structures/4atp_cod7111361.cif",
        "MoS2_optical_analysis/research/atp_raman/scripts/02_v2_build.py",
        "MoS2_optical_analysis/research/atp_raman/slides/render.py",
        "FET_analysis/docs/FET_분석_원리.pptx",
        "MoS2_adsorption_sim/docs/MoS2_흡착_시뮬레이션_원리.pptx",
        "MoS2_optical_analysis/docs/MoS2_분석_원리.pptx",
        "MoS2_optical_analysis/docs/MoS2_Raman PL_분석_사용_매뉴얼.pptx",
    ]
    good_hits = check_paths(good_cases)
    assert not good_hits, f"Unexpected violations on valid paths: {good_hits}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify public-code vs private-data repository hygiene.")
    parser.add_argument("--staged", action="store_true", help="Check only staged git additions/modifications.")
    parser.add_argument("--install-hook", action="store_true", help="Install .git/hooks/pre-commit and exit.")
    parser.add_argument("--self-test", action="store_true", help="Run built-in rule self-tests and exit.")
    args = parser.parse_args(argv)

    if args.self_test:
        _run_self_test()
        print("check_repo_hygiene: self-test passed")
        return 0

    if args.install_hook:
        hook_path = _install_hook()
        print(f"Installed pre-commit hook at {hook_path}")
        return 0

    paths = _git_paths(staged=args.staged)
    violations = check_paths(paths)
    if violations:
        print("Repository hygiene check failed:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1
    scope = "staged" if args.staged else "tracked"
    print(f"check_repo_hygiene: {len(paths)} {scope} file(s) OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
