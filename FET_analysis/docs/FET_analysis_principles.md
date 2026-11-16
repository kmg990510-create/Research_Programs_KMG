# FET transfer 분석 원리

이 문서는 FET Analysis가 transfer 곡선에서 소자 파라미터를 추출하는 방법을 설명한다. [MoS₂ Raman·PL 분석 원리](../../MoS2_optical_analysis/MoS2_분석_원리.pptx)와 같은 흐름으로, 먼저 숫자의 물리적 의미를 살펴보고 수치 추출과 결과 검토로 이어간다. 설정값은 작성 시점의 [config.yaml](../config.yaml), 동작은 분석 코드(기준 커밋 5aa0839)를 따른다.

## 1. Transfer 곡선에서 무엇을 읽는가

Transfer 측정은 드레인–소스 전압 $V_{DS}$를 일정하게 두고 게이트 전압을 바꾸며 $I_D$를 기록한다. 일반적인 접지 소스 측정에서 파일의 $V_G$는 $V_{GS}$와 같다. $I_G$를 함께 기록하면 낮은 드레인 전류가 나타나는 구간에서 게이트 누설의 영향을 점검할 수 있다. Output 측정은 게이트 바이어스를 정하고 드레인 전압을 바꾼다. 현재 프로그램은 두 종류를 분류하며, 파라미터 추출은 transfer에 적용한다. Output에서 접촉저항 $R_C$, 포화 이동도 또는 breakdown 전압을 추출하는 기능은 현재 구현 범위 밖이다.

| 지표 | 읽는 위치 | 해석 |
| --- | --- | --- |
| $I_{\mathrm{off}}$ | 낮은 전류 plateau | 측정한 off 상태의 전류 수준. 장비 바닥 전류나 누설의 영향을 받을 수 있다. |
| $I_{\mathrm{on}}$ | 가장 많이 켜진 게이트 전압 쪽 끝 | 주어진 게이트 전압 범위와 드레인 바이어스에서 얻는 대표 전류다. |
| $g_m$ | 선형 전류축에서 가장 가파른 구간 | 게이트 전압 1 V당 드레인 전류 변화량이다. |
| $V_{\mathrm{th}}$ | $g_m$ 접선의 절편 또는 정해진 전류의 교차점 | 추출 정의에 따라 값이 달라지는 turn-on의 기준 전압이다. |
| SS | 로그 전류축에서 전류가 지수적으로 증가하는 구간 | 전류가 10배 증가하는 데 필요한 게이트 전압이다. |
| $\mu_{\mathrm{FE}}$ | $g_m$과 소자 치수·절연막 정전용량·바이어스 | 선형 영역 모델에서 역산한 field-effect mobility다. |
| $\Delta V_{\mathrm{th}}$ | 같은 측정의 왕복 sweep | sweep 이력에 따른 문턱전압 변화다. |

### 선형 전류축과 로그 전류축

선형 축에서 기울기 $g_m=dI/d u$의 단위는 S(A/V)다. 여기서 $I=|I_D|$이고 $u$는 소자가 켜지는 방향으로 정의한 전압이다. 로그 축에서는 $y=\log_{10}(I/\mathrm{A})$를 그린다. $y=a u+b$이면 $\Delta u=1/a$에서 $I$가 10배 증가하므로 $\mathrm{SS}=1000/a$ mV/dec다. 예를 들어 0.2 V 동안 전류가 두 decade 증가하면 SS는 100 mV/dec다.

### 선형 영역의 전류식과 이동도

누적된 채널 전하를 게이트 overdrive와 면적당 정전용량 $C_{\mathrm{ox}}$로 근사하고, 이동도가 일정한 gradual-channel 모델을 적용하면 다음을 얻는다. $u_{\mathrm{th}}$는 turn-on 좌표에서의 문턱전압이다.

$$
 I \simeq \mu_{\mathrm{FE}} C_{\mathrm{ox}}\frac{W}{L}
 \left[(u-u_{\mathrm{th}})|V_{DS}|-\frac{|V_{DS}|^2}{2}\right]
 \quad\Longrightarrow\quad
 g_m \simeq \mu_{\mathrm{FE}} C_{\mathrm{ox}}\frac{W}{L}|V_{DS}|
$$

$C_{\mathrm{ox}}=\varepsilon_0\varepsilon_r/t_{\mathrm{ox}}$는 평행판 모델이다. $t_{\mathrm{ox}}$를 m로 넣으면 $C_{\mathrm{ox}}$는 F/m²다. 2단자 transfer의 $g_m$에는 접촉저항과 게이트 바이어스에 따른 전하 수송 변화도 반영된다. 특히 4-ATP 처리 전후에 접촉과 채널이 함께 변하면, 추출된 $\mu_{\mathrm{FE}}$ 변화에는 두 효과가 함께 들어갈 수 있다.

## 2. 장비 파일에서 분석 좌표까지

### 장비 파일의 표준화와 바이어스 확인

- Keysight B1500 EasyEXPERT CSV는 파일 하나가 측정 하나다. Keithley 4200A Clarius XLS는 데이터 시트 하나가 측정 하나다.
- Reader는 장비 열 이름을 공통 열 $V_G,V_D,V_S,I_D,I_G,I_S,t$에 대응시킨다. 단위는 V, A, s다. 원래 행 순서와 읽은 전류 부호를 보존한다. 누락된 값과 숫자로 읽을 수 없는 셀은 NaN이다.
- 유한한 전압값끼리 이웃한 차이를 계산한다. 차이의 절댓값이 $10^{-9}$ V보다 큰 비율이 50% 이상이면 해당 전압을 sweep으로 본다. $V_G$만 해당하면 transfer, $V_D$만 해당하면 output이다. 둘 다 해당하거나 둘 다 해당하지 않으면 ‘unknown’으로 분류된다.
- $V_{DS}$는 $V_D-V_S$다. 각 단자에 대해 측정 열의 중앙값, 장비 헤더 바이어스 순서로 값을 찾는다. 둘 다 없는 source는 0 V로 가정하고 출처를 기록한다. drain 값이 없으면 $V_{DS}$는 미확정이다. $V_G$는 파일에서 매핑된 열을 사용하므로, source가 접지되지 않은 데이터에서 해당 열이 이미 $V_{GS}$인지 확인한다.

구현은 [장비 형식 변환과 바이어스 판정](../fet_core/io/tables.py), 열 이름은 [장비별 설정](../config.yaml)에서 확인할 수 있다.

### 극성과 sweep 방향

1. 측정 전체에서 유한한 $V_G$와 양의 $|I_D|$가 있는 점을 $V_G$로 정렬한다. 전압이 높은 쪽 20%의 로그 전류 중앙값에서 낮은 쪽 20%의 중앙값을 뺀다. 차이가 +1 decade 이상이면 n-type, −1 decade 이하면 p-type이다. 중간값은 극성을 확정할 수 없어 ‘unknown’이다. 양 끝 전류가 비슷한 ambipolar 곡선이나 sweep 범위가 짧은 곡선은 이 기준을 통과하기 어렵다.
2. 원래 취득 순서에서 시작 $V_G$로부터 가장 멀어진 전압을 반환점으로 잡는다. 처음부터 반환점까지가 ‘forward’, 반환점부터 끝까지가 ‘backward’다. 반환 전압을 반복 기록하면 첫 점은 forward의 끝, 마지막 점은 backward의 시작으로 사용한다. 한 번만 기록하면 양쪽이 그 점을 공유한다. p-type에서 높은 전압부터 낮은 전압으로 측정해도 첫 구간이 forward다.
3. 각 방향의 분석에 최소 10점이 필요하다. 짧은 복귀 구간에 점이 2–9개면 ‘short_backward_sweep’을 남긴다. 취득 순서에서 주 진행방향의 반대로 움직인 유효 전압 증분이 전체 유효 이웃 증분의 5%를 넘으면 ‘non_monotonic_sweep’을 남긴다. 여러 번 왕복한 데이터는 단일 반환점을 전제로 한 이 분할의 적용 범위를 벗어난다.
4. 분석할 때는 $u=sV_G$로 변환한다. $s=+1$이 n-type, $s=-1$이 p-type이다. 유한한 $u$와 $|I_D|$가 있는 행을 사용하고, 같은 $u$에서 반복 취득한 $|I_D|$와 $|I_G|$는 각각 평균한다. 이후 $u$가 증가하면 두 극성 모두 off에서 on으로 향한다. 결과 전압은 $V_G=su$로 환산한다. 0 A는 선형 계산에 들어갈 수 있으며 로그 전류에서는 NaN으로 처리된다. 정렬·집계 후 전체 점과 양의 전류점이 각각 10개 이상 필요하다.

구현은 [sweeps.py](../fet_core/analysis/sweeps.py)와 [transfer.py](../fet_core/analysis/transfer.py)에 있다.

## 3. 구간별 수치 추출

실제 계산 순서는 전이 구간, on/off 전류, $g_m$과 선형 외삽 $V_{\mathrm{th}}$, 정전류 $V_{\mathrm{th}}$, SS, 이동도, 누설 평가다. 두 방향의 계산이 끝나면 히스테리시스를 계산한다.

### 3.1 전이 구간

각 sweep의 원래 로그 전류에서 5백분위 $P_5$와 95백분위 $P_{95}$를 구한다. 그 차이 $D=P_{95}-P_5$가 1 decade 미만이면 ‘no_gate_modulation’으로 파라미터 추출을 중단한다. $D$는 전이 탐색용 범위다. 아래에서 계산하는 $\log_{10}(I_{\mathrm{on}}/I_{\mathrm{off}})$와 값이 다를 수 있다.

$$
 y_{\mathrm{low}}=P_5+0.10D, \qquad
 y_{\mathrm{high}}=P_5+0.90D
$$

5점 이동 중앙값을 씌운 로그 전류가 $y_{\mathrm{high}}$에 처음 도달하는 점을 전이 끝으로 잡는다. 도달하지 못하면 평활 곡선의 최댓값 위치를 쓴다. 전이 끝 앞에서 $y_{\mathrm{low}}$ 미만인 마지막 점은 off의 끝이다. 그 점이 없으면 ‘off_state_not_reached’를 기록한다. 이동 중앙값은 경계를 찾는 데 쓰고, 오프 구간의 회귀와 SS 회귀에는 평활 전 로그 전류를 사용한다.

### 3.2 Off 전류, on 전류와 on/off 비

**Off 전류.** 전압 간격 중앙값 $\widetilde{\Delta u}$로부터 창의 점 수를 $N_{\mathrm{off}}=\max(5,\lceil 2\,\mathrm{V}/\widetilde{\Delta u}\rceil+1)$로 정한다. 예를 들어 0.5 V 간격이면 5점, 0.1 V 간격이면 21점이다. 불균일한 sweep에서는 창의 실제 **전압 폭**도 결과 열에서 확인할 수 있다.

1. off 끝까지의 연속 창마다 $\log_{10}(I/\mathrm A)$의 표준편차 $\sigma_y$와 최소제곱 직선의 기울기 $a$를 계산한다.
2. $\sigma_y\le0.3$ decade이고 $|a|\le0.1$ decade/V인 창 중 $\operatorname{median}(y)+0.5\sigma_y$가 가장 낮은 창을 고른다. 그 창의 $|I_D|$ 중앙값이 $I_{\mathrm{off}}$다. 방법은 ‘stable_plateau’로 저장한다.
3. 안정 창이 없으면 sweep 전체에서 같은 길이의 창을 검색하고, $|I_D|$ 중앙값이 가장 낮은 창을 ‘lowest_window’로 저장한다. sweep이 너무 짧아 창을 만들 수 없으면 값은 빈 칸이다. 두 경우 모두 ‘off_plateau_not_found’를 남긴다. 측정이 off 상태까지 닿지 않았다면 fallback 전류가 실제 off 전류보다 높을 수 있다.

**On 전류.** $u$가 가장 큰 쪽 5점에서 $|I_D|$의 중앙값을 구한다. 예를 들어 n-type의 $V_G$ 범위가 −40~60 V이고 간격이 0.5 V이면 58~60 V가 사용된다. 따라서 sweep 끝 전압이나 $V_{DS}$가 다른 두 결과의 $I_{\mathrm{on}}$은 측정 조건을 함께 봐야 한다.

두 전류가 모두 양수이면 비율과 decade 값을 저장한다. $\log_{10}(I_{\mathrm{on}}/I_{\mathrm{off}})<2$이면 ‘low_on_off_ratio’다. CSV에는 전류 자체(A)와 폭으로 나눈 on 전류(µA/µm)가 들어간다.

### 3.3 Peak transconductance

인접한 두 점을 바로 미분하면 전류 잡음이 $\Delta u$로 나뉘어 커지고, 단일 스파이크가 peak를 만들 수 있다. 이 프로그램은 각 창에서 일정 간격을 둔 여러 쌍의 기울기를 구하고 중앙값을 사용한다.

1. 정렬된 sweep에서 시작점마다 최소 2 V와 5점을 만족하는 가장 짧은 창을 만든다. $N$점 창에서 $k=\max(1,\lfloor N/4\rfloor)$로 정하고 다음 기울기의 중앙값을 구한다.

   $$
   m_i=\frac{I_{i+k}-I_i}{u_{i+k}-u_i},\qquad g_{m,\mathrm{window}}=\operatorname{median}(m_i)
   $$

2. 창별 기울기에 다시 이동 중앙값을 적용한다. 평활에 쓰는 이웃 창 개수는 유효 창의 점 수 중앙값을 정수화한 뒤 홀수로 맞춘 값이다. 유효한 양의 peak를 얻을 수 없으면 ‘gm_not_extracted’를 남긴다.
3. 각 창의 기울기 오차는 잔차의 중앙절대편차에 기반한 추정값이다. 창별 절편을 $b=\operatorname{median}(I-g_{m,\mathrm{window}}u)$로 두고, $\sigma=1.4826\,\operatorname{median}|I-g_{m,\mathrm{window}}u-b|$와 유효 점 쌍 수 $N_{\mathrm{pairs}}$로 오차를 계산한다.

   $$
   \widehat{\operatorname{SE}}(g_{m,\mathrm{window}})=
   \frac{1.25\sqrt{2}\,\sigma}
   {\operatorname{median}(u_{i+k}-u_i)\sqrt{N_{\mathrm{pairs}}}}
   $$

4. 평활 $g_m$가 최댓값의 50% 이상인 창들의 오차 중앙값을 그 최댓값으로 나눈다. 이 값이 5%를 넘으면 창을 두 배씩 늘려 재계산한다. 확대 후 창은 sweep 폭의 25% 이하여야 한다. 최종 오차가 5%를 넘으면 ‘gm_noisy’를 남기고 추출값은 유지한다. ‘gm_relative_error’는 창 선택과 잡음 평가에 쓰는 값으로, 이동도의 전체 불확도에는 절연막 정전용량, 치수, 접촉 등의 오차도 들어간다.
5. 평활 최댓값의 99% 이상인 첫 창을 선택한다. 평평한 꼭대기에서는 turn-on에 가까운 쪽을 선택하는 셈이다. 선택한 평활 기울기가 결과의 $g_{m,\mathrm{peak}}$다. 이 평활값에 대응하는 이웃 창 전체의 첫 점과 마지막 점 사이에서 절편 $b$를 다시 구한다. 기록하는 peak 전압은 그 두 끝점 전압의 중간값이다.

선택 창의 끝에서 sweep 끝까지 5점 또는 2 V 미만만 남으면 ‘gm_peak_at_sweep_edge’가 붙는다. 하한 가능성을 알리는 참고 사항이며, 이 사유만으로 상태를 ‘attention’으로 올리지는 않는다. $g_m$이 여전히 증가하는 곡선에서는 peak와 이동도가 관측 범위 안의 값이고, 외삽 문턱전압도 sweep 범위에 민감하다.

수치 구현은 [numeric.py](../fet_core/analysis/numeric.py)와 [transfer.py](../fet_core/analysis/transfer.py)에 있다.

### 3.4 문턱전압의 두 정의

**선형 외삽.** $I=g_{m,\mathrm{peak}}u+b$를 0 A까지 외삽한다. x절편은 $u_0=-b/g_{m,\mathrm{peak}}$다. 기본 설정에서 $V_{\mathrm{th,lin}}=s u_0$이다. 선형 영역 식을 쓰면 $u_0=u_{\mathrm{th}}+|V_{DS}|/2$이므로 ‘subtract_half_vds’를 켰을 때는 $V_{\mathrm{th,lin}}=s(u_0-|V_{DS}|/2)$를 기록한다. 켠 상태에서 $V_{DS}$가 없으면 이 문턱전압은 빈 칸으로 남는다. 화면에서는 접선의 0 A 절편과 보정된 마커가 서로 떨어져 보일 수 있다.

**정전류.** 폭 1 µm당 1 nA를 기본 기준으로 사용한다. $W=10\,\mathrm{\mu m}$이면 $I_{\mathrm{ref}}=10\,\mathrm{nA}$다. turn-on 순서에서 이 전류보다 작은 **마지막** 점과 바로 다음 점을 찾는다. 양의 두 전류 사이에서는 로그 전류축에서 보간한다. 왼쪽 점이 0 A인 경우에는 전류축에서 선형 보간한다. 예를 들어 2 V에서 1 nA, 3 V에서 100 nA라면 10 nA에 해당하는 정전류 문턱전압은 2.5 V다. 마지막 점까지 기준보다 낮거나 처음부터 모두 기준 이상이면 값을 비우고 ‘vth_const_current_not_found’를 남긴다.

같은 곡선에서 두 방법의 값이 달라도 정상이다. 정전류 추출은 기준 전류와 폭, 해당 구간의 SS나 누설에 민감하다. 선형 외삽은 최대 기울기가 나타나는 구간과 접선 절편에 민감하다. 비교할 때는 문턱전압 정의, 기준 전류, half-$V_{DS}$ 설정을 맞춘다.

### 3.5 Subthreshold swing

off 끝에서 최대 4점을 더 앞쪽으로 포함하도록 탐색을 시작하고 전이 끝까지 탐색한다. 이 범위에서 연속 5–20점의 모든 후보 창을 대상으로 $y=a u+b$ 최소제곱 직선을 계산한다.

| 조건 | 기본값 | 의미 |
| --- | --- | --- |
| 기울기 $a$ | $>0$ | turn-on 방향으로 전류가 증가한다. |
| 결정계수 $R^2$ | $\ge0.95$ | 선택한 구간이 로그 전류축에서 직선에 가깝다. |
| 직선이 덮는 전류 범위 $a(u_{\mathrm{last}}-u_{\mathrm{first}})$ | $\ge0.5$ decade | 짧은 잡음 구간이나 평평한 구간이 결과로 선택될 가능성을 줄인다. |

조건을 통과한 창 중 $a$가 가장 큰 창, 즉 SS가 가장 작은 창을 저장한다. 창의 전압 양 끝, 점 수, $R^2$, 덮은 decade 수와 누설비 중앙값도 함께 저장한다. 조건을 통과한 창이 없으면 ‘ss_not_extracted’다. 이 SS는 프로그램이 찾은 **국소 최솟값**이다. 서로 다른 gate step에서는 같은 점 수가 서로 다른 전압 폭을 덮으므로, 처리 전후 비교에서는 선택된 창과 측정 간격을 함께 확인한다. 높은 $R^2$는 직선성의 지표이며, 선택 구간의 전류가 채널에 기인하는지는 누설 곡선과 함께 해석한다.

### 3.6 Field-effect mobility

$$
 \mu_{\mathrm{FE}}\,(\mathrm{cm^2\,V^{-1}\,s^{-1}})=
 10^4\frac{g_{m,\mathrm{peak}}}{(W/L)C_{\mathrm{ox}}|V_{DS}|}
$$

기본 치수는 $W=10$ µm, $L=5$ µm, $t_{\mathrm{ox}}=300$ nm, $\varepsilon_r=3.9$다. 이때 $C_{\mathrm{ox}}\simeq1.1510\times10^{-4}$ F/m², 즉 11.51 nF/cm²다. 같은 $g_m$이라도 입력한 $L/W$ 또는 $t_{\mathrm{ox}}/\varepsilon_r$에 비례해 이동도가 달라진다. 예를 들어 실제 SiO₂가 90 nm인데 기본값 300 nm로 계산하면, 나머지가 같을 때 이동도를 약 3.33배 높게 보고한다. 적층 유전체에서 평행판 직렬 모델을 적용할 경우 $C_{\mathrm{ox}}^{-1}=\sum_i t_i/(\varepsilon_0\varepsilon_{r,i})$다. 프로그램에는 이 값과 일치하는 유효 단일막 입력 조합을 사용한다.

- 파일명과 소자 라벨이 같은 transfer 측정끼리 묶어, 0이 아닌 $|V_{DS}|$의 최솟값을 찾는다. 상대 오차 $10^{-6}$ 이내의 측정은 모두 포함하며 각 방향의 이동도를 계산한다. 같은 소자라도 서로 다른 파일로 저장했으면 별도 묶음이 된다. 예를 들어 한 Clarius 파일의 같은 라벨에 0.1 V와 1 V가 있으면 0.1 V에서 계산하지만, 두 바이어스가 서로 다른 B1500 CSV라면 각각 계산 대상이 된다.
- $g_m$가 추출되었고 $V_{DS}$가 없거나 0 V면 ‘vds_missing’으로 이동도는 빈 칸이다. 더 큰 바이어스라면 ‘not_lowest_vds’라는 사유를 기록하고 이동도만 비운다. 최저 바이어스 sweep에서 추출에 실패해도 높은 바이어스로 자동 대체하지 않는다.
- 기본 기준에서 $|V_{DS}|>u_{\mathrm{peak}}-u_0$이면 ‘mobility_outside_linear_regime’을 표시한다. 코드가 이 판단에 쓰는 $u_0$는 half-$V_{DS}$ 보정 전 절편이다. 경고가 있어도 계산값은 남는다. 작은 $|V_{DS}|$를 고르는 규칙과 이 경고는 선형 근사의 적합성을 판단하는 데 함께 쓰인다.

### 3.7 게이트 누설과 히스테리시스

**누설.** 양의 $|I_D|$와 유효한 $I_G$가 함께 있는 전압점에서 $r=|I_G|/|I_D|$를 구한다. off는 off 끝까지, transition은 그 다음 점부터 전이 끝까지, on은 전이 끝 다음 점부터다. 각 구간의 중앙값과 최댓값을 기록하며, 전이 구간에서는 $r>1$인 점의 비율도 기록한다. SS 창의 누설비 중앙값은 별도 열에 남는다.

| 범위 | 자동 판정 |
| --- | --- |
| Transition | 중앙값이 1 이상이면 ‘leakage_dominated_transition’ |
| On | 중앙값이 0.1 이상이면 ‘on_state_leakage’ |
| Off, SS 창 | 수치 기록. 해당 구간의 누설비만으로 발동하는 독립 경고는 없다. |

누설비는 진단용이다. $I_G$를 $I_D$에서 빼거나 누설이 큰 점을 마스킹하는 과정 없이 추출한다. 단자 전류의 비율만으로 누설의 경로나 드레인 전류에 섞인 양을 특정하기 어렵다. $I_G$를 기록하지 않았다면 관련 지표가 비어 있으므로 누설 유무 판정에는 추가 근거가 필요하다.

**히스테리시스.** 같은 측정에서 동일한 정의의 forward와 backward $V_{\mathrm{th}}$가 둘 다 있으면 $\Delta V_{\mathrm{th}}=V_{\mathrm{th,backward}}-V_{\mathrm{th,forward}}$를 계산한다. 두 문턱전압 정의 각각에 적용한다. 예를 들어 forward가 5 V, backward가 8 V이면 +3 V다. 같은 값이 두 sweep 행에 기록되므로 측정별로 별도 통계를 계산할 때는 두 번 세지 않도록 한다. 스윕 속도, 시작·반환점과 대기 시간에 따라서도 차이가 날 수 있다.

## 4. 경고와 결과 판독

| 상태 또는 기록 | 관련 코드 | 확인할 부분 |
| --- | --- | --- |
| ‘invalid’ | ‘insufficient_points’, ‘no_gate_sweep’, ‘no_gate_modulation’ | 유효 점 수, 기록된 게이트 전압, 극성과 로그 전류 변조 폭 |
| ‘attention’ | ‘short_backward_sweep’, ‘non_monotonic_sweep’ | 취득 순서와 실제 sweep 방향 |
| ‘attention’ | ‘off_state_not_reached’, ‘off_plateau_not_found’, ‘low_on_off_ratio’ | off 쪽 전압 범위, 잡음, 장비 전류 바닥, 누설 |
| ‘attention’ | ‘gm_not_extracted’, ‘gm_noisy’, ‘vth_const_current_not_found’ | 선형 곡선의 기울기, 정전류 기준의 실제 교차 |
| ‘attention’ | ‘ss_not_extracted’, ‘leakage_dominated_transition’, ‘on_state_leakage’ | 로그 곡선의 직선 구간과 $I_G$ |
| ‘attention’ | ‘vds_missing’, ‘mobility_outside_linear_regime’ | 기록된 $V_{DS}$와 peak 부근 overdrive |
| 참고 | ‘gm_peak_at_sweep_edge’ | peak 후에 충분한 데이터가 있는지 |

한 sweep에 사유가 여러 개면 가장 심각한 수준으로 상태를 정한다. 경고가 있는 sweep도 일부 지표를 계산할 수 있다. 개별 추출 실패는 빈 값으로 기록한다. $\mathrm{SS}$만 비어 있는 행은 해당 지표의 집계에서 빠지지만, 이동도 등 값이 있는 다른 지표에는 반영될 수 있다. 상태와 사유의 전체 정의는 [results.py](../fet_core/analysis/results.py)에 있다.

1. **Run**에서 $W,L,t_{\mathrm{ox}},\varepsilon_r$와 $V_{\mathrm{th}}$ 옵션을 확인한다. 배치 기본값과 개별 측정에 지정한 치수는 추출에 반영된다.
2. **Devices**의 log plot에서 off 창과 SS 직선, 정전류 마커, $I_G$를 함께 본다. Linear plot에서 $g_m$ 창과 접선, 외삽 $V_{\mathrm{th}}$를 확인한다. 반복 전압이 있으면 분석기는 집계된 절댓값을 사용하고, 화면의 SS 보조선은 표시 구간의 원래 취득점으로 다시 맞추므로 조금 다를 수 있다. 필요하면 sweep별 승인·제외와 메모를 남긴다.
3. **Compare**는 표시 그룹과 sweep 방향별로 비교한다. 자동 상태가 ‘valid’ 또는 ‘attention’이고 검토 결정이 ‘rejected’가 아닌 행이 집계된다. ‘approved’는 자동 ‘invalid’를 뒤집지 않는다. 그룹의 포함 sweep 수와 실제 지표별 ‘count’는 결측 때문에 다를 수 있다.
4. **Finalize**에서 결과를 내보낸다. 아래 표의 파일을 함께 보관하면 입력과 설정을 기준으로 숫자를 다시 추적할 수 있다.

| 파일 | 확인할 내용 |
| --- | --- |
| ‘results_summary.csv’ | sweep별 추출값, 사용한 구간과 방법, 상태, 사유, 결정, 집계 여부 |
| ‘group_summary.csv’ | 그룹·방향별 sweep 수, 포함 수, 지표별 count·median·mean·std·min·max |
| ‘warnings.csv’ | 파일 읽기와 분석에서 발생한 경고 |
| ‘measurements.csv’ | 표준화한 측정점과 곡선 분류 |
| ‘transfer_curves/’ | 그룹·방향별 Origin용 곡선 표. ‘rejected’ sweep은 제외하고 원래 $I_D$ 부호를 사용한다. |
| ‘run_metadata.json’ | 버전, 확인 가능한 git commit, 입력 파일 SHA-256, 전체 설정, 유효 분석 옵션, 기본 치수와 검토 설정 |
| ‘review.json’ | 검토 과정에서 저장하는 치수·옵션 변경, 승인·제외 및 메모 |

구현은 [집계와 검토 반영](../fet_core/pipeline.py), [그룹 통계](../fet_core/report/summary.py), [내보내기](../fet_core/report/export.py)에 있다.

## 5. 합성 sweep에서 계산값 따라가기

[합성 데이터 생성기](../fet_core/synth.py)로 n-type 왕복 곡선을 만들고 현재 기본 설정으로 계산했다. 입력은 $V_{DS}=1$ V, $V_G=-40\rightarrow60\rightarrow-40$ V, 0.5 V 간격, $W=10$ µm, $L=5$ µm, $t_{\mathrm{ox}}=300$ nm, $\varepsilon_r=3.9$다. 생성기에 $V_{\mathrm{th}}=5$ V, SS = 2000 mV/dec, 이동도 = 20 cm²/(V·s), off floor = $10^{-13}$ A, $|I_G|=10^{-12}$ A와 backward의 +3 V 이동을 넣었다. 무작위 잡음은 추가하지 않았다.

| 항목 | Forward 결과 | 계산 흔적 |
| --- | --- | --- |
| 전이 경계 | −7.0~12.5 V | 5–95백분위 차이 8.36 decade에 10%·90% 기준 적용 |
| $I_{\mathrm{off}}$ | $1.00\times10^{-13}$ A | −40~−38 V, 5점, ‘stable_plateau’ |
| $I_{\mathrm{on}}$ | 24.86 µA | 58~60 V, 5점 중앙값. 폭 정규화 2.486 µA/µm |
| On/off | $2.49\times10^8$ | 8.396 decade |
| Peak $g_m$ | 0.4577 µS | 7.5~11.5 V가 접선 결정에 사용된 구간. 중심 9.5 V |
| 선형 외삽 $V_{\mathrm{th}}$ | 4.964 V | 접선의 0 A 절편. half-$V_{DS}$ 보정은 기본 설정에서 꺼져 있다. |
| 정전류 $V_{\mathrm{th}}$ | 1.807 V | 10 nA 교차점 |
| SS | 2001.74 mV/dec | −2.5~−0.5 V, 5점. 피팅 직선이 약 1.00 decade를 덮는다. |
| 이동도 | 19.88 cm²/(V·s) | $10^4(0.4577\times10^{-6})/[2(1.1510\times10^{-4})(1)]$ |
| 히스테리시스 | +3.000 V | Backward 선형 외삽값 7.964 V에서 forward 값 4.964 V를 뺀다. 정전류 방식도 +3.000 V다. |

이 예에서 off 구간의 누설비 중앙값은 약 10이고 전이 구간 중앙값은 약 $2.6\times10^{-5}$다. 자동 상태는 ‘valid’다. off 전류를 논문이나 시료 비교에 사용할 때는 자동 상태와 함께 off 창의 $I_G$를 확인할 이유가 여기에 있다. 이 사례는 합성 곡선에서 추출 과정과 단위를 확인한 예다. 잡음, 전류 계단, p-type, 누설, sweep 끝의 peak를 포함한 검증 사례는 [test_transfer.py](../tests/test_transfer.py)에 있다.

## 6. 4-ATP 처리 전후의 transfer를 비교할 때

| 관찰 | 먼저 확인할 값 | 가능한 해석 |
| --- | --- | --- |
| n-type 곡선이 왼쪽으로 이동 | 같은 $V_{DS}$·방향·방법의 두 $V_{\mathrm{th}}$, SS, 누설 | 같은 전류가 더 낮은 게이트 전압에서 나온다. 전하 전달, 계면 전위, trap 점유, 접촉 변화가 각각 기여할 수 있다. |
| $\mu_{\mathrm{FE}}$ 증가 | 같은 바이어스의 $g_{m,\mathrm{peak}}$, 추출 창, $C_{\mathrm{ox}}$, $W/L$ | 같은 전압 변화에서 드레인 전류가 더 크게 변한다. 채널 수송과 접촉의 기여를 구분하려면 별도 측정이 필요하다. |
| $I_{\mathrm{on}}/I_{\mathrm{off}}$ 증가 | On과 off 전류를 각각 확인. 특히 ‘lowest_window’ 여부, $I_G$, 끝 전압 | 증가가 on 전류 향상에서 왔는지, off 전류 감소에서 왔는지 판단할 수 있다. |
| SS 또는 히스테리시스 개선 | SS 창의 전압·누설, sweep 속도와 시작·끝 전압 | 동일 조건에서 문턱 부근 전류 제어와 sweep 이력의 변화를 비교할 수 있다. |

같은 치수·바이어스·sweep 조건에서 N₂ anneal 기준군과 4-ATP 처리군을 비교하면 어닐링 기여가 섞이는 정도를 줄일 수 있다. $V_{\mathrm{th}}$가 이동했을 때는 끝 전압 기준 $I_{\mathrm{on}}$과 함께, 공통 $V_G-V_{\mathrm{th}}$에서의 전류도 원곡선에서 비교할 수 있다. CSV의 $I_{\mathrm{on}}$은 끝 5점의 정의를 사용한다.
