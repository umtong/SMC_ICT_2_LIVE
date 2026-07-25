# Durable decisions

## Evaluation

- 미래정보 누수 방지, 시간적 인과성, 계산 정확성, 현실적인 체결과 과최적화 방지는 모든 전략의 기본 조건이다.
- 기본 조건을 위반한 결과는 무효로 처리한다.
- 의존성이 바뀌지 않은 공통 검증은 재사용하고 변경된 부분과 새 가설을 검증한다.
- 오류 수정 또는 무효화 후 수익성 탐색으로 복귀한다.

## Work selection and reuse

- 가장 고정보가치인 미해결 작업은 Work Claim에 목적·범위·의존성 지문, 기준 revision, lease와 branch를 기록한다.
- 동일 범위의 활성 작업이나 기존 결과가 있으면 재사용하고 미해결 부분으로 이동한다.
- 독립 재현은 기존 작업과 다른 방법 또는 확인 가치를 기록한다.
- 자료, 데이터, 차트, 코드, 백테스트, 결과와 검증 증거는 stable ID와 dependency fingerprint로 재사용한다.

## Folder and action lifecycle

- 지속 폴더와 반복 행동은 목적·입력·산출물·소비자·사용 조건·완료 조건·정리 규칙을 가져야 한다.
- 역할이 중복되면 하나의 canonical path로 통합한다.
- 생산자나 소비자가 없는 폴더·스크립트·템플릿은 제거하거나 역할을 다시 정의한다.
- 가설의 canonical Drive 위치는 `03_RESEARCH/10_HYPOTHESES`다.
- 임시 inbox·download staging·quarantine은 장기 보관소로 사용하지 않는다.
- Result Registry와 Validation Cache를 사용하지 않는 PR은 해당 없음의 이유를 기록한다.

## Data

- 공개된 모든 정보와 자료를 자유롭게 사용한다.
- 작업에 사용하거나 재사용 가치가 높은 자료를 한 번 등록하고 보존한다.
- 저장한 원본은 변경하지 않고 가공본은 버전 관리한다.
- 전체 영상은 영상 자체가 고유한 연구 가치를 제공할 때만 저장한다.

## Storage

- GitHub에는 실행 규칙, 설정, 코드, 스키마, manifest, checksum, 의존성 지문과 재현 가능한 요약을 저장한다.
- Google Drive에는 라이브 문서, 원시·대형 자료, 데이터, Run Report, 검증 증거와 snapshot을 저장한다.
- 자격증명, 개인 식별자와 비공개 Drive binding을 공개 저장소에 저장하지 않는다.

## State update

- 공통 상태와 Champion 변경 전 최신 revision과 관련 열린 PR을 확인한다.
- 기준 revision이 바뀌었으면 재평가·rebase·충돌 조정 후 검증된 PR로 반영한다.
- 서로 다른 데이터·비용·체결·평가 계약의 결과를 직접 순위 비교하지 않는다.

## Current milestone

- revision: 4
- Folder·Action Contract: active
- Champion: none
