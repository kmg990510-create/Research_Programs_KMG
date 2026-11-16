# Streamlit UI 개편 원칙과 구현 준비 계획

작성일 2026-11-16  
상태 — 계획 수립 완료, 구현 착수 전  
대상 — Research_Programs_KMG 통합 GUI와 세 프로그램의 독립 실행 GUI

## 1. 목표와 적용 범위

승인된 Streamlit 시안의 고정 헤더, 간결한 사이드바, 본문 단계 이동, 결과 중심 배치를 현재 분석 프로그램에 적용한다. 현재 구현된 계산·검토·수동 편집·저장·내보내기·환경별 기능을 모두 보존한다. 시안의 합성 데이터와 계산식은 실제 프로그램에 이식하지 않는다.

이번 작업의 산출물은 이 문서다. 애플리케이션, 분석 코드, 설정, 실험 데이터, 기존 AGENTS.md의 변경은 구현 단계에서 진행한다. 현재 작업 트리에는 진행 중인 Adsorption 개발과 문서 변경이 있으므로 구현 시작 시 당시 작업 상태를 다시 기록한다.

## 2. 화면 배치 원칙

| 영역 | 배치 기준 | 실제 항목 |
| --- | --- | --- |
| 앱 고정 헤더 | 모든 프로그램에서 유지되는 정체성과 전역 정보 | Research Programs KMG, 필요한 실행 상태 |
| 사이드바 | 여러 단계에서 유지되는 작업 대상 | 프로그램 선택, 활성 Batch 또는 Report |
| 본문 상단 | 프로그램 내 작업 단계 | Run, Devices/Review/Viewer, Compare, Finalize |
| 본문 필터 행 | 결과를 보며 반복해서 바꾸는 표시 범위 | Groups, Sweep, Status, Surface, Molecule |
| 결과 영역 위 보기 선택 | 동일 작업의 표현 방식 | Detail/Gallery, Statistics/Overlay/Summary |
| 결과와 같은 영역 | 판단에 필요한 조작 | 승인·제외·메모, 수동 refit, map 선택 |
| 해당 영역의 설정 버튼 | 자주 바꾸지 않는 표시 옵션 | Figure settings, Manage groups |
| Run 본문 | 계산 결과를 바꾸는 입력 | 치수, 유전율, 모델, optimizer, MD 조건 |

- 헤더는 전체 화면 폭을 차지하며 스크롤 중 유지한다. 사이드바와 본문 시작 위치를 헤더 아래로 맞춘다. Streamlit 메뉴, 접기 버튼, 키보드 포커스, dialog/popover를 가리지 않는다.
- 사이드바의 프로그램 및 작업 대상 구획은 기본으로 펼친다. 사용자가 반복해서 접고 펴야 하는 구조를 만들지 않는다.
- 화면 필터는 단계 이동 후에도 유지한다. 필터가 적용 중이라는 사실과 표시 개수를 결과 가까이 보여준다.
- 빈 필터의 의미, rejected 표시 기본값, 요약 포함 정책은 현재 프로그램의 동작을 먼저 기록하고 보존한다. 시안의 기본값을 그대로 적용하지 않는다.
- 큰 단계 이동, 하위 보기 선택, 설정 버튼은 간격과 형태로 계층을 구별한다. 동일한 모양의 탭 세 줄을 쌓지 않는다.
- 설정 popover를 닫아도 적용된 상태를 유지한다. 계산이 필요한 입력의 Apply와 편집 저장의 기존 동작을 구별한다.
- 이름·순서 편집은 Manage groups에 둔다. Summary table의 원본 식별자는 표시 이름과 함께 추적할 수 있어야 한다.
- 데이터 없음, 실패, 부분 완료, 경고 다수, 긴 이름, 많은 그룹도 정상 사용 상태로 설계한다.
- 넓은 화면에서 목록–그래프–판정을 배치하고 좁아지면 판정을 그래프 아래에 배치한다. 창 폭 때문에 그래프가 읽기 어려워지는 경우 목록 폭과 그래프 배치를 먼저 조정한다.
- 1920×1080, 1366×768 및 더 좁은 창에서 검증한다. 고정 헤더와 입력 영역이 결과를 과도하게 밀어내지 않는지 확인한다.

## 3. 현재 규칙과의 정합성

구현 첫 커밋에서 루트 AGENTS.md의 UI 규칙을 먼저 개정하고 프로그램별 문서를 맞춘다. 아래는 개정할 내용이며 현재 운영 규칙의 즉시 변경을 뜻하지 않는다.

| 기존 규칙 | 개정 방향 |
| --- | --- |
| 사이드바에서 데이터·결과 선택, 본문에서 결과 표시 | 사이드바는 활성 작업 대상, 본문은 필터·분석 입력·결과·판정 |
| 1) Report, 2) Filters, 페이지별 구획 | 프로그램/Report 또는 Batch 구획을 기본 펼침. 필터는 본문 공통 행 |
| Figure size를 사이드바에 배치 | 결과 영역의 Figure settings로 입력 위치 이동 |
| 모든 입력을 번호 붙은 사이드바 구획에 배치 | 사이드바 항목에만 구획 규칙 적용. 본문 입력은 업무 영역에 배치 |

기존 labkit.plot_theme, finish_figure, show_figure, 크기 지정, PNG/SVG, 3배 카메라 저장 계약을 유지한다. Grid와 Image format의 전체 그래프 적용 범위도 유지한다. 특정 페이지의 설정 창으로 이동해도 전역 옵션이라는 설명을 표시한다. 화면 장식의 청록색을 데이터 의미별 색상 규칙에 덮어쓰지 않는다.

과학적 설정은 기존 YAML을 사용한다. 화면 테마와 간격은 별도 UI 설정 또는 공통 스타일에 둔다. 기존 파라미터 저장·승인 방식의 변경은 UI 이전과 분리해 추적한다.

## 4. 페이지별 기능 보존 및 목적지

### FET Analysis

| 현재 경로 | 새 위치 | 보존할 기능 |
| --- | --- | --- |
| fet_gui/Run.py | Run 본문 | 배치 추가, 파일 저장, W/L/산화막 두께/유전율, 개별 소자 geometry, Apply/Reset, Vds/2 보정, constant-current 기준, Advanced |
| fet_gui/state.py | 사이드바 Batch 및 본문 공통 필터 | 배치 선택, sweep/status/groups, rejected 표시, 기존 상태 관리 |
| pages/1_Devices.py | Devices | 표 선택, Detail/Gallery, 갤러리 열 수, 곡선 클릭 이동, 이전/다음, linear/log 곡선, 추출값, 경고 설명, Approve/Reject/Clear, 메모와 자동 다음 이동 |
| pages/2_Compare.py | Compare | Statistics/Overlay/Summary table 보기, Quantities, 채널 폭 정규화 µA/µm, 그룹 이름·순서 |
| pages/3_Finalize.py | Finalize | 결과 파일 쓰기, ZIP 다운로드, 요약과 재현성 정보 |

Devices의 경고는 판정 패널에서 짧게 표시하고 상세 설명은 같은 화면에서 펼친다. 경고로 그래프가 화면 밖으로 밀려나는 상황을 줄인다. Summary와 통계는 기존 included 판정 경로를 공유한다.

### MoS₂ Optical Analysis

| 현재 페이지 | 새 위치 | 보존할 기능 |
| --- | --- | --- |
| Main.py | Overview | report 요약, 원본·수정 포함 JSON, 파라미터 CSV, 설정 snapshot |
| 1_Run_Analysis.py | Run | Raman/PL, run type, 폴더/업로드/ZIP, mapping 분할, 설정과 모델 선택, worker·진행 표시·로그, 결과 Bin 이동·복구·영구 삭제 |
| 2_Flagged_Spectra.py | Review | RMSE/R²/delta 필터, 편집과 기존 Apply Edits |
| 3_All_Spectra_Viewer.py | Viewer → Spectra | ID 검색, index 이동, map/model 필터, 축 범위, 모델 override, Si 확인, desktop manual editor, web manual refit와 auto fit, 수동 결과 삭제, 메모, candidate/원본/fit summary |
| 4_Map_Viewer.py | Viewer → Map | map/parameter 선택, ratio, 상태·rejected 조건, mouse selection, 선택점 결정/메모, Figure style 및 preset, 좌표·색 범위·원점, status map |
| 5_Model_Comparison.py | Compare → Models | 상태·rejected 필터, 비교 metric 및 모델 결과 |
| 6_Sample_Comparison.py | Compare → Samples | report 다중 선택, modality, reference, 중심·오차 방식, strain/doping 계수, 점 구름·isoline, eps-n/Absolute Positions/n vs FWHM/FWHM Pair/LO Ratio, PL 온도 비교, heatmap와 스타일 |
| 7_Finalize.py | Finalize | reviewer, 확인 항목, manifest 쓰기, 최종 JSON/CSV/manifest 다운로드 |

Viewer의 Spectra/Map은 하위 탐색으로 표현한다. Samples 안의 다섯 plot 선택은 차트 영역의 선택 컨트롤로 배치해 단계 탭과 구별한다. 여러 Report를 비교하는 입력은 Compare 본문에 둔다. 단일 활성 Report를 쓰는 Viewer와 데이터 범위가 다름을 표시한다. desktop editor의 로컬 전용 조건과 web refit 경로를 모두 보존한다.

### MoS₂ Adsorption Sim

| 현재 페이지 | 새 위치 | 보존할 기능 |
| --- | --- | --- |
| ads_gui/Run.py | Run | 배치 생성, substrate/surface/molecule/업로드, calculator/D3, binding scan/no-D3, site/orientation/azimuth, optimizer/fmax/steps, MD 조건·seed·MD only |
| ads_gui/state.py | 작업 대상 및 공통 필터 | batch, surface/molecule/status/groups/rejected, 분자 파일 trash·복구·영구 삭제 |
| 1_Poses.py | Poses | Detail/Gallery, 이전/다음, 판정·메모, 3D 모드, 초기 구조·거리·relaxation, 2D top/side, 수렴곡선, 에너지 분해, MD trajectory 선택과 viewer |
| 2_Compare.py | Compare | Statistics, Energy & Binding Curves, Surface Site Map, Summary & Group Names, decomposition, curve view, surface 선택 |
| 4_Coverage_Dimer.py | Viewer의 Coverage & Dimer 접근 항목 | N=1–4 coverage/distances, 3D/2D, pairwise matrix, periodic XY tiling, ghost, molecule 색, 거리 highlight, precursor N=2, disulfide view |
| 3_Finalize.py | Finalize | 결과 파일·구조·메타데이터 및 ZIP |

Coverage/Dimer 파일은 현 통합 app.py의 페이지 목록에 없다. 독립 실행 진입점의 등록 여부를 구현 시작 시 확인하고 통합·독립 모두에서 접근할 수 있게 계획한다. 실제 미완료 계산 기능을 UI에서 완성된 기능으로 표시하지 않는다. 해당 페이지의 독자적인 study 데이터 선택은 본문에 두고 배치와의 관계를 표시한다.

## 5. 코드 변경 계획

1. 구현 착수 시 git 상태, 파일 해시, 실행 환경과 Streamlit 버전, 기존 URL 및 독립 진입점을 기록한다. 현재 미커밋 변경과 사용자의 진행 중인 계산을 보존할 작업 브랜치를 준비한다.
2. 루트 AGENTS.md와 프로그램별 UI 항목을 위 원칙에 맞춰 개정한다.
3. 통합 app.py와 독립 진입점의 탐색을 같은 화면 구성에 연결한다. 기존 st.Page/URL/뒤로가기·직접 링크 동작을 유지할 수 있도록 탐색 경로를 설계한다. 단순 segmented_control 재실행으로 모든 분석 페이지를 동시에 실행하지 않는다.
4. 공통 헤더와 작업 단계 배치를 두 프로그램 이상에서 재사용하는 범위로 labkit에 추가한다. 기존 theme/sidebar/figure_size API를 활용한다. state.py에는 데이터 상태와 선택 상태를 유지하고 페이지는 배치 위주로 둔다.
5. FET Run → Devices → Compare → Finalize를 첫 수직 구현 단위로 완성한다. 기존 실제 배치 복사본으로 읽기·선택·검토·내보내기까지 확인한다.
6. Optical Overview/Run/Review/Viewer, 이어 Compare/Finalize를 이전한다. 큰 페이지는 현재 함수와 데이터 흐름을 보존하며 components로 나눈다.
7. Adsorption의 Poses·MD·Coverage/Dimer를 포함하여 이전한다. 기존 완료 결과를 우선 사용해 시각 검증한다.
8. 통합·독립 실행, 로컬·클라우드 업로드/다운로드 경로를 점검한다. exe 빌드는 별도 요청 시 진행한다.

시안의 fixed 헤더는 Streamlit DOM에 대한 CSS 선택자를 사용했다. 실제 도입 시 지원 버전을 확정하고 공식 테마/API로 가능한 부분을 우선 구현한다. 필요한 DOM 의존 CSS는 공통 모듈 한 곳으로 제한하고 header/sidebar/dialog 겹침을 검증한다.

## 6. 상태·데이터·성능 계약

- 프로그램·배치·report·선택 항목·보기·필터 상태를 구별한다. widget이 화면에서 사라져도 필요한 선택값이 지워지지 않게 보관한다.
- 배치 전환 시 존재하지 않는 항목 선택은 유효한 항목으로 바꾸고 다른 배치의 판정·메모가 섞이지 않게 한다.
- 그림 옵션과 탐색 조작이 fitting, relaxation, MD를 재시작해서는 안 된다. 버튼의 단일 실행과 기존 작업 상태를 보존한다.
- 요약 필터와 사용자 결정은 기존 분석 모델 및 results_frame/포함 판정 함수를 사용한다.
- 캐시는 입력·설정·모델·수정 기록 변화에 맞춰 무효화한다. fragments 도입은 실제 재실행 비용을 확인한 뒤 범위를 정한다.
- 수치·단위·NaN·경고·수동 수정 이력·출력 열·파일 이름·메타데이터를 기존 계약과 대조한다.
- 실제 데이터는 원본을 읽고, 쓰기가 필요한 검증은 작업용 복사본과 임시 출력 경로를 사용한다. 데이터와 생성 결과는 git에 넣지 않는다.

## 7. 검증과 완료 조건

| 검증 | 확인할 결과 |
| --- | --- |
| 기능 도달성 | 위 표의 각 기능에 진입 경로가 있고 현재 지원 조건에서 사용 가능 |
| 수치 동등성 | 동일 입력/설정/결정에서 표·그래프·export의 값, 단위, NaN, 포함 행이 일치 |
| 편집 연속성 | 승인/제외/clear/메모/모델 override/refit 후 페이지 이동 및 재열기에서 기존 저장 계약 충족 |
| 탐색 | 통합·독립 실행, URL 직접 접근, 프로그램 전환, 뒤로가기, 활성 batch/report 유지 |
| 그래프 | zoom/선택/Gallery 이동, map 선택, 3D/MD, PNG/SVG·3배 저장·크기·Grid 확인 |
| 환경 | 로컬 폴더/desktop editor, 클라우드 업로드/다운로드, 계산 backend 미설치 시 표시 |
| 화면 | 고정 헤더 스크롤, sidebar 접기, popover/dialog, 긴 경고/이름, 좁은 창, 키보드 조작 |
| 출력 | 기존 CSV/JSON/ZIP와 구조 파일, finalize manifest 및 재현성 메타데이터 계약 유지 |

기존 FET/Adsorption tests/test_gui.py, Optical tests/test_gui_shared_logic.py와 해당 분석 테스트를 사용한다. 변경으로 새롭게 위험해지는 탐색·상태 보존만 필요한 회귀 검증을 추가한다. 실데이터 검증은 테스트가 원본 폴더에 의존하도록 만들지 않는다.

완료 증거는 기능 대응표 체크, 대표 실제 데이터의 변경 전후 수치 비교, 주요 화면 캡처, 테스트 결과다. 자동 테스트만으로 외관 검증을 대체하지 않는다.

## 8. 착수 전 남은 확인 및 현재 준비 상태

- 페이지와 주요 components/state의 UI 호출을 조사하여 기능 대응표를 작성했다. 동적 생성 입력과 전체 callbacks의 세부 매핑은 각 페이지 이전 직전 다시 확인한다.
- 원시 데이터와 결과 디렉터리의 존재를 확인했다. 데이터 내용 분석과 실제 계산 재실행은 이번 계획 단계에서 수행하지 않았다.
- Adsorption은 진행 중인 미커밋 기능이 있어 구현 착수 시 기능 목록을 다시 대조한다.
- 브랜치 생성 docs/ui-redesign-plan은 .git/refs/heads 디렉터리 쓰기 권한 오류로 실패했다. 계획 문서는 현재 작업 폴더에 작성했으며 커밋은 하지 않았다. 다음 구현 시 쓰기 가능한 checkout 또는 작업 환경에서 브랜치를 먼저 준비한다.
- 이 문서의 화면 대응과 보존 계약을 구현의 기준으로 사용한다. 실제 기능을 제거하거나 분석 방식을 바꾸는 결정은 별도 변경으로 기록한다.

## 9. 다음 세션용 자료

- [세션 인계 및 실행 지시](UI_HANDOFF.md)
- [시각 규격과 화면별 예시](UI_VISUAL_SPEC.md)
- [실행형 참고 시안](ui_reference/README.md)

재현 기준은 실행형 소스와 시각 규격을 함께 사용한다. 시안의 기능적 한계와 실제 구현 시 보완점은 UI_VISUAL_SPEC.md의 6절에 기록했다.
