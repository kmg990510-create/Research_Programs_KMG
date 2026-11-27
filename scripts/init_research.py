"""Initialize a standardized private research workspace under <Program>/research/<topic>/."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import re
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[1]

PROGRAMS: tuple[str, ...] = (
    "MoS2_optical_analysis",
    "FET_analysis",
    "MoS2_adsorption_sim",
)

COMMON_DIRS: tuple[str, ...] = (
    "configs",
    "engine",
    "scripts",
    "tests",
    "logs",
    "figures",
    "reports",
    "scratch",
)

PROGRAM_EXTRA_DIRS: dict[str, tuple[str, ...]] = {
    "MoS2_optical_analysis": ("slides", "slides/templates"),
    "FET_analysis": (),
    "MoS2_adsorption_sim": ("molecules", "mlip", "dft"),
}

_TOPIC_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")

REPORT_TEMPLATE = """# YYYY-MM-DD — <단계 또는 분석 제목>

- **주제:** `<topic>`
- **프로그램:** `<program>`
- **실행 스크립트 / 설정:** `scripts/...`, `configs/...`
- **로그:** `logs/...`

## 1. 목적 및 질문

- 무엇을 확인/비교하려는가?

## 2. 입력 · 방법 · 설정 요약

- 입력 데이터 / 구조:
- 주요 파라미터(온도, 컷오프, 계산기/피팅 모델 등):
- 적용된 가정 및 한계:

## 3. 정량 결과 요약

| 항목 | 값 | 단위 | 상태 / 비고 |
| --- | --- | --- | --- |
| | | | |

## 4. 해석 및 다음 단계

- 관찰된 경향(과장·단정 표현 금지):
- 남은 불확실성 / 검증 필요 사항:

## 5. 생성 산출물

- 테이블/메타데이터:
- 그림:
- 로그:
"""


def init_research_workspace(
    *,
    repo_root: Path,
    program: str,
    topic: str,
    today: str | None = None,
) -> Path:
    """Create standard private workspace folders and starter docs for a research topic."""
    if program not in PROGRAMS:
        raise ValueError(f"Unsupported program {program!r}; choose one of {PROGRAMS}")
    if not _TOPIC_RE.match(topic):
        raise ValueError(
            f"Topic {topic!r} must match ^[a-z0-9][a-z0-9_-]{{1,63}}$ (lowercase, digits, _, -)"
        )

    prog_dir = repo_root / program
    if not prog_dir.is_dir():
        raise FileNotFoundError(f"Program directory not found: {prog_dir}")

    topic_dir = prog_dir / "research" / topic
    created_dirs = list(COMMON_DIRS) + list(PROGRAM_EXTRA_DIRS[program])
    for rel in created_dirs:
        (topic_dir / rel).mkdir(parents=True, exist_ok=True)

    day_str = today or date.today().isoformat()

    readme_path = topic_dir / "README.md"
    if not readme_path.exists():
        extra_lines = "".join(f"- `{d}/` — 프로그램별 연구 작업 폴더\n" for d in PROGRAM_EXTRA_DIRS[program])
        readme_path.write_text(
            f"# {topic} (Private Research Workspace)\n\n"
            f"- **프로그램:** `{program}`\n"
            f"- **생성일:** {day_str}\n"
            "- **규범:** [RESEARCH_GUIDE.md](../../../RESEARCH_GUIDE.md) 참고 (`research/` 전체 git 제외)\n\n"
            "## 폴더 구조\n\n"
            "- `configs/` — 연구 전용 YAML 및 입력 구조\n"
            "- `engine/` — 공용 코어 편입 전 연구 전용 모듈\n"
            "- `scripts/` — 단계별 실행 스크립트\n"
            "- `tests/` — 연구 전용 테스트\n"
            "- `logs/` — 실행 표준 출력 로그\n"
            "- `figures/` — 그림 파일\n"
            "- `reports/` — 단계별 `.md` 보고서 및 발표 자료\n"
            "- `scratch/` — 일회성 임시 스크립트 (정리 대상)\n"
            f"{extra_lines}\n"
            "## 실행 이력\n\n"
            "| 날짜 | 작업 / 스크립트 | 보고서 | 핵심 요약 |\n"
            "| --- | --- | --- | --- |\n",
            encoding="utf-8",
        )

    plans_path = topic_dir / "PLANS.md"
    if not plans_path.exists():
        plans_path.write_text(
            f"# PLANS — {topic}\n\n"
            f"- **생성일:** {day_str}\n\n"
            "## 연구 목표 및 가설\n\n"
            "- 목표:\n"
            "- 검증할 가설:\n\n"
            "## 단계 체크리스트\n\n"
            "- [ ] Step 1: 입력 및 설정 검증 (`configs/`)\n"
            "- [ ] Step 2: 1차 스크리닝 / 탐색 실행 및 `reports/` 기록\n"
            "- [ ] Step 3: 정밀 검증 및 최종 정리\n",
            encoding="utf-8",
        )

    tmpl_path = topic_dir / "reports" / "TEMPLATE_report.md"
    if not tmpl_path.exists():
        tmpl_path.write_text(
            REPORT_TEMPLATE.replace("<topic>", topic).replace("<program>", program),
            encoding="utf-8",
        )

    return topic_dir


def _run_self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for prog in PROGRAMS:
            (root / prog).mkdir()
            out = init_research_workspace(repo_root=root, program=prog, topic="demo_topic_01", today="2026-11-27")
            for sub in COMMON_DIRS + PROGRAM_EXTRA_DIRS[prog]:
                assert (out / sub).is_dir(), f"Missing {sub} for {prog}"
            assert (out / "README.md").is_file()
            assert (out / "PLANS.md").is_file()
            assert (out / "reports" / "TEMPLATE_report.md").is_file()
            # Idempotent re-run preserves existing README/PLANS
            (out / "README.md").write_text("custom-note", encoding="utf-8")
            init_research_workspace(repo_root=root, program=prog, topic="demo_topic_01", today="2026-11-27")
            assert (out / "README.md").read_text(encoding="utf-8") == "custom-note"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Initialize a standardized private research topic folder.")
    parser.add_argument("--program", choices=PROGRAMS, help="Target program folder name.")
    parser.add_argument("--topic", help="Research topic folder name (lowercase, digits, _, -).")
    parser.add_argument("--self-test", action="store_true", help="Run built-in self-test in a temp dir.")
    args = parser.parse_args(argv)

    if args.self_test:
        _run_self_test()
        print("init_research: self-test passed")
        return 0

    if not args.program or not args.topic:
        parser.error("--program and --topic are required unless --self-test is specified")

    topic_dir = init_research_workspace(repo_root=REPO_ROOT, program=args.program, topic=args.topic)
    print(f"Initialized research workspace: {topic_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
