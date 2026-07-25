# SMC_ICT_2_LIVE

지속적인 트레이딩 연구, 자료·데이터 재사용, 실험 재현성과 동시 작업 충돌 방지를 위한 프로젝트 저장소다.

## 시작 순서

1. `config/project.toml`
2. `instructions/project-instructions.md`
3. `control/current-state.md`
4. `control/ranking.json`
5. 수행하려는 범위와 관련된 Work Claim·Result·Validation·Source·Dataset·Entity·Run Report·열린 PR
6. `prompts/goal-worker.md`

## 전략 순위

하드 유효 전략과 포트폴리오 후보를 순위표에 기록한다. 현재 1위는 목표 달성 인증이 아니라 프로젝트 전체 목표에 가장 가까웠던 결과다.

가장 중요한 기준은 현실 비용 후 일평균 기하성장률의 1% 목표 격차다. 생존 조건을 위반한 후보는 원시 수익률만으로 생존 조건을 충족한 후보를 앞설 수 없다. 비슷한 목표 격차는 낙폭·회복, 청산·꼬리, 집중도, 독립 거래 수, 체결 강건성, 자본 효율과 비교 신뢰도로 구분한다.

순위는 연구 우선권이나 보호 대상을 만들지 않는다. 작업은 전체 목표 기여도와 정보가치로 선택한다. 판정 가능한 결과는 일반 Result 기록과 버전관리로 한 번 보존하고, 순위표는 result ID와 비교 정보만 갱신한다.

## 작업 흐름

1. Project State와 전략 순위를 읽고 수행할 범위를 정한다.
2. 관련된 기존 작업과 산출물만 검색한다.
3. 중복 비용이 크거나 재사용 가치가 높은 작업에만 Work Claim을 만든다.
4. 기존 자료·데이터·차트·코드·결과·검증 증거를 재사용한다.
5. 후보 가치와 의사결정 중요도에 비례해 단계형 검증을 적용한다.
6. 가장 높은 목표 기여도와 정보가치를 가진 작업을 수행한다.
7. 판정 가능한 전략 결과가 생기면 목표 근접도로 순위표를 갱신한다.
8. 공용·재사용 가능한 변경은 브랜치·검증·PR로 반영하고, 중요한 체크포인트는 Run Report로 남긴다.
9. 상태 변경 전 최신 revision과 열린 PR을 다시 확인한다.

## 저장 위치

- **GitHub:** 실행 규칙, 설정, 코드, 스키마, 스크립트, 작은 manifest, 의존성 지문, 재현 가능한 요약과 milestone 상태
- **Google Drive:** 라이브 Work Claim·Run Report, 원시·대형 자료, 시장 데이터, 실행 산출물과 검증 증거
- **ChatGPT Project:** 현재 작업에 필요한 작은 hot context

공개된 정보와 자료를 자유롭게 사용한다. 실제 작업에 사용했거나 다시 찾을 가능성이 높은 자료만 등록하고 재사용 가능하게 보존한다. 전체 영상은 영상 자체가 고유한 연구 가치를 제공할 때만 저장한다.

## 검사

```bash
python scripts/validate_project.py
python -m pytest
python scripts/build_context_bundle.py
```

## 다른 프로젝트에 재사용

```bash
python scripts/init_project.py \
  --project-id new-project \
  --project-name NEW_PROJECT \
  --github-repository owner/NEW_PROJECT \
  --drive-root-name NEW_PROJECT
```

비공개 Google Drive 폴더 ID는 Git에서 제외되는 `config/project.local.toml`에 기록한다.

## 현재 상태

`ACTIVE_RESEARCH / revision 7`: 현재 1위는 `FIRST-20260725-HIGH-RESISTANCE-SWEEP-C232AE43`이며, stage는 `EXPLORATORY`, target status는 `NOT_MET`이다. 이 순위는 provisional 비교 정보일 뿐 검증 완료, 실사용 가능성 또는 연구 우선순위를 의미하지 않는다.
