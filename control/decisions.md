# Durable decisions

## Evaluation

- 미래정보 누수 방지, 시간적 인과성, 계산 정확성, 현실적인 체결과 과최적화 방지는 모든 전략의 기본 조건이다.
- 기본 조건을 위반한 결과는 하드 무효로 처리한다.
- 경제적 기준 미달과 하드 무효를 구분한다.
- 검증 깊이는 후보의 경제적 가능성과 의사결정 중요도에 비례시킨다.
- 초기 후보는 치명적 오류와 기본 비용으로 빠르게 선별하고, 계좌·전략 선택이나 실사용 판단을 실질적으로 바꿀 후보에게만 검증을 확대한다.
- 의존성이 바뀌지 않은 공통 검증은 재사용하고 변경된 부분과 새 가설을 검증한다.

## Champion

- Champion은 목표 달성 인증이나 실사용 승인이 아니라 현재 가장 우수한 hard-valid 전략 또는 포트폴리오 후대를 가리키는 순위 포인터다.
- 비교 가능한 hard-valid 후보가 하나 이상 있으면 현재 Champion을 선정한다.
- 목표 달성 여부, 검증 단계, 목표 격차와 실사용 가능성은 Champion 지위와 분리해 기록한다.
- 판정 가능한 새 전략 결과는 현재 Champion과 비교하고, 더 우수하면 포인터를 즉시 교체한다.
- 비교 조건의 정규화가 불완전하면 비교 신뢰도와 취약점을 표시한 provisional research Champion을 유지한다.
- 부분 구성요소의 선두는 component leader로 별도 관리한다.
- Champion 지위는 연구 우선권, 추가 검증 의무, 보호 예산 또는 기본 개선 경로를 부여하지 않는다.
- 작업은 Champion 주변 개선 여부가 아니라 목표 기여도와 정보가치로 선택한다.
- 판정 가능한 결과는 Champion 여부와 무관하게 일반 Result 기록과 버전관리로 한 번 남기며, 포인터 교체 때 별도 백업·복제·재검증을 반복하지 않는다.

## Work selection and reuse

- Project State와 Champion을 먼저 읽고 수행 범위와 관련된 기록만 검색한다.
- 중복 비용이 크거나 재사용 가치가 높은 작업에만 Work Claim을 만든다.
- 짧고 국소적인 확인·분석·메모는 기존 작업 기록 안에서 처리한다.
- 동일 범위의 활성 작업이나 기존 결과가 있으면 재사용하고 미해결 부분으로 이동한다.
- 독립 재현은 비정상적 성과, 결과 충돌, 계좌·전략 선택 변경 또는 실사용 의사결정에 필요한 경우에 수행한다.

## Data

- 공개된 모든 정보와 자료를 자유롭게 사용한다.
- 실제 작업에 사용했거나 다시 찾을 가능성이 높은 자료만 최소 메타데이터로 등록하고 보존한다.
- 사용하지 않은 검색 결과는 등록하지 않는다.
- 저장한 원본은 변경하지 않고 가공본은 버전 관리한다.
- 전체 영상은 영상 자체가 고유한 연구 가치를 제공할 때만 저장한다.

## Output and storage

- 공용·재사용 가능한 코드, 설정, 평가 계약, 데이터 변환, 공통 상태와 재현 산출물은 GitHub 브랜치·검증·PR로 반영한다.
- 짧은 탐색 메모와 재사용되지 않을 임시 분석을 위해 별도 PR을 만들지 않는다.
- Drive에는 라이브 Work Claim, 전체 Run Report와 대형 자료를 저장하고, GitHub에는 milestone 상태와 재현 가능한 요약을 저장한다.
- 완전한 Run Report는 목표 달성, 시간제한, 판정 가능한 결과, 접근 전환 또는 상태 변경 시 작성한다.

## State update

- 공통 상태와 Champion 변경 전 최신 revision과 관련 열린 PR을 확인한다.
- 기준 revision이 바뀌었으면 재평가·rebase·충돌 조정 후 검증된 PR로 반영한다.
- 새 후보가 우수하면 Champion이 가리키는 result ID와 순위 정보를 갱신한다.
- 서로 다른 데이터·비용·체결·평가 계약의 결과는 정규화하거나 비교 불확실성을 명시한다.

## Current milestone

- revision: 6
- Champion: `CHAMPION-20260725-HIGH-RESISTANCE-SWEEP-C232AE43`
- Champion stage: `EXPLORATORY`
- target_status: `NOT_MET`
- Champion operational effect: rank pointer only; no research priority or repeated preservation work
