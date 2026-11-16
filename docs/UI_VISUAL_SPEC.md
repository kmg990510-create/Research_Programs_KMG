# UI 시각 규격 및 화면별 예시

작성일 2026-11-16. 재현 기준은 docs/ui_reference의 실행형 시안이다.

## 1. 공통 스타일

| 역할 | 기준 |
| --- | --- |
| 고정 헤더 | #14273b, 전체 화면 폭, 높이 48 px |
| 본문 배경 | #f2f6fa |
| 사이드바·입력 보조 배경 | #e7eef5 |
| 강조·현재 선택 | #067674 |
| 본문 글자 | #14273b |
| 테두리 | #ccd9e5, 얇은 선 |
| 모서리 | 8 px 수준 |
| 그래프 내부 | 흰 배경, 기존 labkit 논문 스타일 |
| UI 글꼴 | Streamlit sans-serif 기준 |
| 과학 그래프 | 기존 labkit Arial 및 크기 규격 |

주요 버튼에 강조색을 사용한다. 데이터의 의미별 색과 상태 색은 기존 labkit 계약을 유지한다. 시안의 그래프 스타일로 분석 프로그램의 테마를 덮어쓰지 않는다.

## 2. 화면 계층

1. 앱 전체 고정 헤더.
2. 프로그램 제목과 Run / Devices / Compare / Finalize 단계 이동.
3. 결과 범위를 고르는 공통 필터 한 줄.
4. 현재 단계 제목.
5. 단계 내부 보기 선택 및 설정 버튼.
6. 보기별 입력.
7. 실제 결과.

헤더 아래에서 sidebar와 본문이 시작한다. Streamlit 자체 메뉴, sidebar 접기, dialog/popover 및 키보드 포커스가 가려지지 않아야 한다. 프로그램 제목은 약 40 px, 단계 제목은 약 32 px의 시안 위계를 기준으로 하되 작은 화면에서는 여백과 제목 크기를 조정한다.

단계 이동과 결과 보기와 설정이 같은 모양의 탭 세 줄로 누적되지 않게 한다. 기능을 추가할 때도 이 계층에서 위치를 정한다.

## 3. 사이드바와 필터

사이드바는 프로그램 선택과 활성 Batch/Report를 기본 펼침으로 둔다. 보고서를 여러 개 고르는 Compare 입력은 Compare 본문에 둔다. 필터는 결과 위에서 항상 보이게 하며 활성 범위와 표시 개수를 보여준다. 보기 전환 후 선택은 유지한다.

Figure settings는 그래프 가까이 둔다. Grid와 Image format은 기존의 모든 그래프 적용 범위를 유지하고, 현재 그래프 크기는 대상이 무엇인지 표시한다. PNG/SVG, 크기 지정, 카메라 저장 3배 해상도를 보존한다.

## 4. FET 예시

### Run

활성 Batch는 sidebar에 둔다. 본문은 파일 입력 → 공통 geometry → 개별 geometry → 분석 설정 → 실행/Apply 순서다. W, L, 산화막 두께, 유전율은 항상 보인다. 기존 저장 시점과 계산 옵션을 모두 유지한다.

### Devices

- 넓은 화면의 시작 열 비율은 목록 1 : 곡선 4 : 판정 1.6이다.
- 목록은 개수, 소자·sweep·상태를 보여준다. 실제 기존 dataframe 선택 기능을 보존한다. 시안의 radio 목록으로 축소하지 않는다.
- 중앙에는 선택 소자 제목과 linear/log 곡선을 나란히 둔다.
- 오른쪽에는 핵심 지표, 품질 경고, Approve/Reject/Clear와 메모를 둔다.
- 시안의 Exclude 표기는 운영 Reject와 의미가 같으며 기존 rejected 저장 값을 유지한다.
- 상세 수치·경고 설명은 같은 화면에서 펼친다.
- Detail/Gallery는 Devices 내부 보기다. Gallery 열 수는 해당 보기의 Figure settings에 둔다.
- 좁은 창에서는 곡선을 위아래로 놓고 판정 패널을 곡선 아래로 옮긴다. 전환 폭은 실제 화면 검증 후 정한다.
- 긴 목록은 목록 영역 안에서 스크롤할 수 있게 하여 그래프와 판정 버튼에 접근하기 쉽게 한다.

### Compare

| 행 | 왼쪽 | 오른쪽 |
| --- | --- | --- |
| 보기 | Statistics / Overlay / Summary table | Manage groups |
| Statistics 입력 | Quantities | Figure settings |
| Overlay 입력 | Current normalization, axis scale 등 기존 옵션 | Figure settings |
| 결과 | 통계 2열 또는 전체 폭 overlay/표 | 필요한 범례 |

Groups/Sweep/Status는 데이터 범위, Quantities는 표시할 물리량을 고른다. 통계에 포함된 개수를 결과 바로 위에 보여준다. 실제 포함 여부는 기존 included 함수를 사용한다.

Manage groups는 그룹 표시 이름과 순서를 수정하며 기존 영속 저장 경로에 연결한다. 표시 이름과 원본 식별자의 관계를 유지한다.

### Finalize

활성 작업 대상, 포함/제외 개수, 생성할 파일과 재현성 정보, 저장·다운로드 조작을 배치한다. 기존 파일 생성·확인 절차를 유지한다.

## 5. Optical과 Adsorption 예시

- Optical Viewer의 Spectra/Map은 하위 탐색이다. Map 내부의 Selection/Figure style은 map 가까운 도구로 배치하여 계층을 구별한다.
- Optical Compare의 Models/Samples 선택 아래, Samples의 eps-n 등 차트 종류는 결과 영역에서 고른다. report 다중 선택과 reference 선택을 본문에 유지한다.
- Adsorption Poses의 Detail/Gallery 및 MD 기능을 유지한다. trajectory와 frame 조작은 3D viewer 가까이에 둔다.
- Adsorption Compare의 Energy & Binding Curves, Surface Site Map은 기존 보기로 유지한다. 그룹 이름 편집은 Manage groups로 옮긴다.
- Coverage & Dimer의 study 선택과 세 하위 보기를 유지하고 통합 메뉴에도 Viewer 범주에서 도달할 수 있는 경로를 둔다.

## 6. 시안에서 실제 구현으로 보완할 항목

| 시안 | 실제 구현 요구 |
| --- | --- |
| 합성 데이터·구조 | 기존 reader·분석 결과·구조 사용 |
| Run/Finalize 비활성 예시 | 현재 입력·계산·export 전체 연결 |
| Optical/Adsorption의 정적 단계 표시 | 실제 페이지 및 기존 URL 연결 |
| 세션 내 판정 | 기존 영속 저장·수정 이력 연결 |
| 단순화된 FET 옵션 | normalization, Gallery, 상세 수치 등 전체 보존 |
| DOM CSS 기반 헤더 | 지원 버전 확인, 공통 모듈 격리, 팝업·접기·스크롤 검증 |
| 예시 반응형 배치 | 실제 긴 이름과 많은 경고에서도 읽을 수 있는 배치 |

## 7. 화면 검수

브라우저 확대율 100%, 1920×1080 및 1366×768에서 동일 조건으로 비교한다.

- Hub의 카드 높이·Open 버튼 정렬과 헤더 위치.
- Devices의 소자 선택→곡선 확인→판정 동선.
- Compare의 단계/보기 구별과 그룹 설정 위치.
- Statistics 아래로 스크롤한 상태의 헤더 고정.
- 경고가 많은 소자에서 그래프와 판정 조작의 접근성.
- Sidebar 접힘 상태에서 헤더·접기 버튼·본문 정렬.
- Popover/dialog를 열었을 때 겹침과 키보드 포커스.
- 긴 파일명, 빈 결과, 많은 그룹, 부분 완료·오류 상태.

새 기능의 위치는 공통 틀 안에서 결정한다. 기능 보존을 위해 배치를 바꾸면 사유와 비교 화면을 남긴다.
