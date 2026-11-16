# UI 개편 세션 인계서

작성일 2026-11-16. 상태는 구현 준비다. 이 문서는 다른 세션에서 사용자가 확인한 시안을 재현하고 실제 기능을 이전하기 위한 시작점이다.

## 읽을 순서

1. 루트 AGENTS.md 및 대상 프로그램 AGENTS.md
2. docs/UI_REDESIGN_PLAN.md — 기능 보존·페이지 대응·구현 순서
3. docs/UI_VISUAL_SPEC.md — 배치와 시각 기준
4. docs/ui_reference/app.py 및 .streamlit/config.toml — 최신 실행형 시안

시안은 프로젝트 docs에 복사한 독립 앱이다. 운영 코드에서 import하지 않는다. 숫자와 구조는 합성 데이터이며 과학적 기준으로 사용하지 않는다.

## 실행

Windows에서 docs/ui_reference/Run_Preview.cmd를 실행한다. 기존 프로젝트 FET_analysis/.venv의 Python을 우선 사용하며 없으면 py 명령을 사용한다. 기본 URL은 http://127.0.0.1:8766 이다.

포트가 사용 중이면 기존 프로세스를 종료하지 않고 다른 포트로 실행한다. 저장소 루트 PowerShell에서 다음 순서로 입력한다.

    $python = (Resolve-Path FET_analysis/.venv/Scripts/python.exe).Path
    Push-Location docs/ui_reference
    & $python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8767 --server.headless true --browser.gatherUsageStats false
    Pop-Location

테마 적용을 위해 작업 디렉터리를 docs/ui_reference로 지정한다. Streamlit 1.67.0, Plotly 7.1.0에서 확인한 시안이며 다음 환경의 버전 호환성은 구현 전에 확인한다.

## 직접 확인할 경로

1. Program Hub의 전체 폭 헤더, 세 카드, 그래프와 Open 버튼 정렬.
2. FET Analysis → Devices에서 Groups를 INTL185로 선택하고 목록–곡선–판정의 배치 확인.
3. Compare로 이동하여 필터 유지와 Statistics / Overlay / Summary table 전환 확인.
4. Quantities 변경, Figure settings 열기, Manage groups에서 이름·순서 변경.
5. Statistics의 아래쪽까지 스크롤하고 sidebar를 접어 헤더 고정 확인.
6. Optical 온도 선택, Adsorption 위치 선택과 구조 회전.
7. 작은 창에서 배치 확인. 시안의 좁은 창 동작까지 완성품으로 간주하지 말고 시각 규격에 따라 개선.

## 다음 구현 세션에 전달할 지시문

> 이 저장소의 UI 개편을 진행해줘. 먼저 docs/UI_HANDOFF.md, docs/UI_REDESIGN_PLAN.md, docs/UI_VISUAL_SPEC.md와 루트 및 프로그램별 AGENTS.md를 읽어줘. docs/ui_reference의 실행형 시안을 열어 승인된 배치·색·간격을 직접 확인한 뒤 작업해줘.
>
> 기존 구현 기능을 모두 살리면서 새 화면을 적용하는 작업이야. 미커밋 변경을 확인하고 보존해줘. 시안의 합성 데이터·계산식을 운영 코드에 가져오지 말고 기존 분석 함수와 저장 계약을 사용해줘.
>
> 루트 AGENTS.md의 사이드바·필터·Figure settings 규칙을 계획과 일치시키는 것부터 시작해줘. FET의 Run → Devices → Compare → Finalize를 첫 구현 단위로 완성하고 실제 배치 복사본으로 수치·판정·출력의 동등성을 확인해줘. 이어 Optical과 Adsorption의 전체 기능 대응표를 완료해줘.
>
> 기능과 외관을 함께 검증해줘. 1920×1080과 1366×768에서 같은 조건의 시안과 구현 화면을 비교하고, 긴 이름·다수 경고·빈 결과·페이지 전환·필터 유지·팝업 겹침을 확인해줘. 주요 단계마다 완료 기능과 남은 검증을 알려줘.
>
> Git 작업은 새 세션의 권한과 제공 도구를 확인해줘. 이전 세션의 .git 쓰기 실패가 계속된다고 가정하지 마. 가능한 정상 작업 경로로 진행하고 실제 차단된 작업은 정확히 알려줘.

## 인계 상태와 검증 한계

현재는 문서와 실행형 참고 자료를 준비한 단계다. 실제 운영 UI 개편은 아직 수행하지 않았다.

이전 세션에서 docs/ui-redesign-plan 브랜치 생성은 .git/refs/heads 쓰기 권한으로 실패했다. 새 세션은 실제 권한을 다시 확인한다. 기존 작업 트리에는 다른 개발 변경이 있으므로 무관한 파일을 되돌리거나 일괄 커밋하지 않는다.

기능 대응표는 페이지 및 주요 components/state의 정적 UI 호출을 조사한 결과다. 동적으로 생성되는 입력과 callback·저장 부수효과는 각 페이지 이전 직전 코드와 테스트를 읽어 추가 확인한다.
