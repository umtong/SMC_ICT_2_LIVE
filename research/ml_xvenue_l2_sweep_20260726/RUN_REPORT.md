# RUN-20260726-ML-XVENUE-L2-SWEEP-001

현재 1위는 `FIRST-20260725-DYNAMIC-STATE-021FBAB6`, 검증 단계는 `EXPLORATORY`, 비용 후 일평균 기하성장률은 `0.0573077%`, 1% 기준 대비 `0.9426923%p/일` 부족하며, 현재 기록된 하드 유효 후보 중 목표 격차가 가장 작다는 이유로 유지된다. 이번 결과는 모델 AUC가 구조적 거리 기준선보다 낮고 비용 자격 행동이 2개뿐이며 모두 손실이라 순위를 바꾸지 않는다.

## 작업 범위

한 개의 SMC/ICT 사건만 사용했다. 직전 완료 Bybit BTCUSDT 5분 범위의 고점 또는 저점 중 한쪽만 다음 블록에서 침범한 뒤, 한 개 HGBT와 한 개 isotonic calibrator가 Binance Futures 상위 5호가 추가·철수·불균형·microprice·공격 체결과 Bybit raid/reclaim 상태를 읽어 continuation, reversal 또는 flat을 결정했다.

- continuation: 같은 방향 0.5 범위 확장 목표, 반대 범위 경계 손절
- reversal: untouched 반대 범위 경계 목표, 같은 방향 0.5 범위 확장 손절
- 진입: 의사결정 100ms 뒤 첫 실행 가능 Bybit bid/ask
- 행동 게이트: 24bp 비용 후 기대값이 추가 5bp를 초과할 때만
- 종료: 구조적 목표 또는 손절뿐이며 elapsed-time 종료 없음
- 계좌: 10,000 USDT, 거래당 계획 손실 1%, 3x notional cap, prior-60s turnover 0.5% capacity, 한 글로벌 슬롯

## 데이터와 단계

Tardis 공개 표준화 자료의 `local_timestamp`를 정보 가용 시각으로 사용했다.

- train: 2022-01-01, 2022-03-01, 2022-05-01
- isotonic calibration: 2022-07-01
- untouched fit confirmation: 2022-09-01, 2022-11-01
- conditional development: 미개봉
- 2024-2026: 미개봉

24개 원천 파일, 47,491,039개 원천 행과 1,112개 완결 sweep 사건을 처리했다. 확인 구간은 380개 사건이며 미해결 사건은 전체에서 1개였다.

## 모델 결과

| 지표 | HGBT + isotonic | 구조적 거리 기준선 |
|---|---:|---:|
| 확인 AUC | 0.506025 | 0.559632 |
| Brier | 0.202496 | 0.283315 |
| AUC 향상 | -0.053608 | 기준 |
| Brier skill | +0.285264 | 기준 |

Brier는 개선됐지만 양성 비중 74.21%의 평균확률 보정 효과였고 순위 판별력은 기준선보다 악화됐다. 비용 후 EV 게이트를 통과한 행동은 reversal 2개뿐이었다.

## 계좌 결과

| 비용 | 거래 | 평균 bp | 중앙값 bp | 총수익 | 샘플일 기하성장 | MDD | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| 12bp | 2 | -23.9956 | -23.9956 | -1.1103% | -0.5567% | 1.1103% | 0.0 |
| 18bp | 2 | -29.9956 | -29.9956 | -1.3890% | -0.6969% | 1.3890% | 0.0 |
| 24bp | 2 | -35.9956 | -35.9956 | -1.6676% | -0.8373% | 1.6676% | 0.0 |

두 행동은 모두 2022-09-01에 발생했고 승리 거래가 없었다. 상위 승자 제거 후 결과도 동일했다.

## 게이트 판정

통과:

- positive Brier skill
- 확인 resolved event 200개 이상
- unresolved share 10% 이하

실패:

- AUC lift 0.01 이상
- 24bp 거래 80개 이상
- 24bp 평균·중앙값·PF·총수익 양수
- 18bp 상위 승자 제거 수익 양수
- 확인일 2개 이상 양수
- 상위 5개 승자 기여 40% 이하
- 상위 승자 제거 후 샘플일 기하성장 1% 이상

따라서 `RES-20260726-ML-XVENUE-L2-SWEEP-001`은 hard validity `PASS_FATAL_SCREEN_ONLY`, economic status `BELOW_GATE`, ranking role `NOT_RANK_ELIGIBLE_PRE2024_FATAL_SCREEN`이다.

## 재사용 증거와 검증

- GitHub PR #148
- GitHub Actions run `30197813475`
- workflow artifact `8630674842`
- artifact SHA-256 `d74dd3576d265b0061e0341a5be3e97317099a0d30a7681e22c15b36b03ddd21`
- source manifest SHA-256 `8327a20cbe7e9ec6d36f66284d87942521e13c48f6390fbc0510fb335373eee3`
- 인과·지연·양 장벽 불리 판정·비용 단조성·글로벌 슬롯·flat 허용·상위 승자 제거 재라우팅 테스트 통과
- 원천 결과 파일 SHA-256 전체 재검증 통과
- 주문 제출 0건

## 실패 원인과 폐기 경계

Binance 표시 L2는 Bybit raid의 구조적 목적지 순서를 기준선보다 더 잘 구분하지 못했다. 또한 24bp와 추가 5bp를 넘는 사건이 사실상 없었다. 따라서 동일 데이터 단위에서 특징량, 모델, 보정법, EV 마진, raid 깊이 또는 임계값을 인접 조정하지 않는다. 레버리지와 위험률 탐색도 열지 않는다.

## 생성·변경 산출물

- `research/ml_xvenue_l2_sweep_20260726/RESULT.json`
- `research/ml_xvenue_l2_sweep_20260726/VALIDATION_ATTESTATION.json`
- 본 Run Report
- 분할 해시 운송 실행기, 사전등록, causal tests, GitHub Actions workflow
- Drive Work Claim·Result Registry·Validation Cache·Dataset Registry와 불변 evidence artifact

## Work Claim 상태

`CLM-20260726-1849-ML-XVENUE-L2-SWEEP-001`을 판정 가능한 음성 결과로 `REPORTED` 처리한다. 현재 1위, revision 11 전략 순위와 live-order permission은 변경하지 않는다.

## 남은 병목과 다음 정확한 시작점

현재 반복되는 병목은 단기 가격·호가 상태 모델이 비용 규모를 넘는 사건을 만들지 못한다는 점이다. 다음 실행은 같은 sweep 또는 L2 특징을 조정하는 것이 아니라, **거래 이전에 관측되는 강제적·비가격 정보가 구조적으로 수십 bp 이동을 유발하는 단일 사건**으로 전환한다. 새 범위는 기존 활성 Work Claim과 겹치지 않는지 먼저 확인하고, 한 사건·한 모델·한 구조적 payoff만 고정해 24bp fatal gate부터 실행한다.
