# CLAUDE.md

이 저장소의 공통 UI·개발 원칙은 **[AGENTS.md](AGENTS.md)** 에 있다. 작업 전에 읽는다.
프로그램별 규칙은 각 폴더의 `AGENTS.md`를 따른다 ([MoS2_optical_analysis/AGENTS.md](MoS2_optical_analysis/AGENTS.md), [FET_analysis/AGENTS.md](FET_analysis/AGENTS.md), [MoS2_adsorption_sim/AGENTS.md](MoS2_adsorption_sim/AGENTS.md)).
통합 Streamlit 진입점은 루트 [app.py](app.py) (`Run_Lab_GUI.cmd`)다.

## 절대 규칙 (공개 레포 위생)

- 모든 측정 원본·시뮬레이션/분석 결과·로그·그림·보고서·`PLANS.md` 및 **결과가 하드코딩된 발표 생성 스크립트(`build_*pptx*.py`, `build_deck.py`)**는 각 프로그램 `data/` 아래에만 둔다.
- `docs/DEV_LOG.md`, `AGENTS.md`, `research/<topic>/README.md`, `docs/PLAN.md`에는 코드·방법·설계·테스트만 적고 미공개 연구 수치·시료 관찰·결론을 쓰지 않는다.
- git 추적 파일에 `_v2`, `_updated`, `_final`, `_review` 접미를 붙이지 않으며, 테스트는 `data/` 파일에 의존하지 않는다.
- 커밋 전 `python scripts/check_repo_hygiene.py` 통과를 확인한다(`.git/hooks/pre-commit` 자동 점검).
