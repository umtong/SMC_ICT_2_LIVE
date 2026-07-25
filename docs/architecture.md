# Architecture

## 저장 계층

- 실행 규칙은 작업 행동을 정의한다.
- TOML 설정은 저장소 복사본을 프로젝트에 연결한다.
- Google Drive는 라이브 문서, Work Claim, Run Report, registry와 대형 자료를 보관한다.
- GitHub는 버전된 규칙, 코드, provenance, manifest, 의존성 지문, 재현 증거와 상태를 보관한다.
- ChatGPT Project는 활성 작업과 hot context를 제공한다.

## 작업 충돌 방지

작업 시작 전 최신 상태, 활성 Work Claim, 결과·검증·자료 registry와 열린 PR을 확인한다. 작업 목적·범위·의존성 지문, 기준 revision, lease와 branch를 Work Claim에 기록한다.

동일 범위의 활성 작업은 기존 산출물을 재사용하고 미해결 부분으로 이동한다. 독립 재현은 기존 작업과 다른 방법 또는 확인 가치를 기록한다.

각 실행은 고유 Run Report와 작업 브랜치를 사용한다. 공통 상태 변경 전 최신 revision을 다시 확인하고, 오래된 기준이면 재평가·rebase·충돌 조정 후 검증된 PR로 반영한다.

## 재사용과 검증

자료, 데이터셋, 차트, 특징량, 코드 산출물, 결과와 검증 증거는 stable ID와 의존성 지문으로 식별한다. 의존성이 같으면 기존 산출물과 검증 증거를 재사용한다. 검증은 변경된 코드·데이터·가정과 새로운 가설 위험에 집중한다.

## 다른 프로젝트에 재사용

`config/project.toml`에는 공개 binding을 기록한다. 비공개 Drive 폴더 ID는 Git에서 제외되는 `config/project.local.toml`과 Drive의 `00_PROJECT_BINDING`에 기록한다. 저장소를 복사한 뒤 `scripts/init_project.py`로 binding을 바꾼다.
