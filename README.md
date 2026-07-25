# SMC_ICT_2_LIVE

지속적인 트레이딩 연구, 자료·데이터 재사용, 실험 재현성과 동시 작업 충돌 방지를 위한 프로젝트 저장소다.

## 시작 순서

1. `config/project.toml`
2. `instructions/project-instructions.md`
3. `control/current-state.md`
4. `control/champion.json`
5. 수행하려는 범위와 관련된 Work Claim·Result·Validation·Source·Dataset·Entity·Run Report·열린 PR
6. `prompts/goal-worker.md`

## Champion

Champion은 목표 달성 인증이 아니라 현재 가장 우수한 hard-valid 전략 또는 전략 포트폴리오 후보다. 검증 단계, 목표 달성 여부, 목표 격차와 실사용 가능성은 별도로 기록한다. 판정 가능한 새 전략 결과는 현재 Champion과 비교하며, 더 우수하면 즉시 교체한다.

## 작업 흐름

1. Project State와 Champion을 읽고 수행할 범위를 정한다.
2. 관련된 기존 작업과 산출물만 검색한다.
3. 중복 비용이 크거나 재사용 가치가 높은 작업에만 Work Claim을 만든다.
4. 기존 자료·데이터·차트·코드·결과·검증 증거를 재사용한다.
5. 후보 가치에 비례해 단계형 검증을 적용한다.
6. 판정 가능한 전략 결과를 현재 Champion과 비교한다.
7. 공용·재사용 가능한 변경은 브랜치·검증·PR로 반영하고, 중요한 체크포인트는 Run Report로 남긴다.
8. 상태 변경 전 최신 revision과 열린 PR을 다시 확인한다.

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

`ACTIVE_RESEARCH / revision 5`: 현 research Champion은 `CHAMPION-20260725-HIGH-RESISTANCE-SWEEP-C232AE43`이며, stage는 `EXPLORATORY`, target status는 `NOT_MET`이다. 이 후보는 현재 비교 기준일 뿐 검증 완료나 실사용 가능성을 의미하지 않는다.
