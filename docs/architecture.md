# Architecture

## 저장 계층

- 실행 규칙은 모든 작업의 목표와 기본 행동을 정의한다.
- TOML 설정은 저장소를 프로젝트와 machine contract에 연결한다.
- Google Drive는 live control, 재사용 자료·데이터, Run Report와 대형 산출물을 보관한다.
- GitHub는 버전된 규칙, 코드, provenance, manifest, 의존성 지문, 재현 증거와 작은 상태를 보관한다.
- ChatGPT Project는 활성 작업과 hot context를 제공한다.

## 폴더·행동 계약

`config/folder-contract.github.toml`, `config/folder-contract.drive.toml`, `config/action-contract.toml`은 지속 폴더와 반복 행동의 목적·입력·산출물·소비자·사용 조건·완료 조건·보존 규칙을 정의한다. `docs/folder-action-contract.md`는 사람이 읽는 요약이다.

폴더는 생산자와 소비자가 모두 있어야 한다. 역할이 겹치면 하나의 canonical path로 통합한다. 빈 폴더는 `must_not_be_empty`, `ready_on_demand`, `prefer_empty`, `prefer_absent` 중 하나로 명시한다.

## 작업 충돌 방지

작업 시작 전 최신 상태, 활성 Work Claim, 결과·검증·자료 registry와 열린 PR을 확인한다. 작업 목적·범위·의존성 지문, 기준 revision, lease와 branch를 Work Claim에 기록한다.

동일 범위의 활성 작업은 기존 산출물을 재사용하고 미해결 부분으로 이동한다. 독립 재현은 기존 작업과 다른 방법 또는 확인 가치를 기록한다.

각 실행은 고유 Run Report와 작업 브랜치를 사용한다. 공통 상태 변경 전 최신 revision을 확인하고, 오래된 기준이면 재평가·rebase·충돌 조정 후 검증된 PR로 반영한다.

## 재사용과 검증

자료, 데이터셋, 차트, 특징량, 코드 산출물, 결과와 검증 증거는 stable ID와 의존성 지문으로 식별한다. 의존성이 같으면 기존 산출물과 검증 증거를 재사용한다. 검증은 변경된 코드·데이터·가정과 새로운 가설 위험에 집중한다.

Result Registry와 Validation Cache는 단순히 존재하는 표가 아니다. PR이 재사용 가능한 결과나 검증 증거를 만들면 해당 entry를 기록하고, 만들지 않았다면 PR에 해당 없음의 이유를 적는다.

## 다른 프로젝트에 재사용

`config/project.toml`에는 공개 binding을 기록한다. 비공개 Drive 폴더 ID는 Git에서 제외되는 `config/project.local.toml`과 Drive의 `00_PROJECT_BINDING`에 기록한다. 저장소를 복사한 뒤 `scripts/init_project.py`로 binding을 바꾼다.
