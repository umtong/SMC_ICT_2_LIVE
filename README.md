# SMC_ICT_2_LIVE

지속적인 트레이딩 연구, 자료·데이터 재사용, 실험 재현성과 동시 작업 충돌 방지를 위한 프로젝트 저장소다.

## 시작 순서

1. `config/project.toml`
2. `instructions/project-instructions.md`
3. `control/current-state.md`
4. `control/champion.json`
5. `control/work-claims.csv`
6. `control/result-registry.jsonl`
7. Source·Dataset·Entity Registry
8. `prompts/goal-worker.md`

## 작업 흐름

1. 최신 상태, Work Claim, 결과·검증·자료 레지스트리와 열린 PR을 확인한다.
2. 가장 고정보가치인 미해결 범위를 선점한다.
3. 기존 자료·데이터·차트·코드·결과·검증 증거를 재사용한다.
4. 작업 브랜치에서 구현·실험·검증하고 append-only Run Report를 작성한다.
5. 상태 변경 전 최신 revision을 다시 확인하고 검증된 PR로 반영한다.

## 저장 위치

- **GitHub:** 실행 규칙, 설정, 코드, 스키마, 스크립트, 작은 manifest, 의존성 지문, 재현 가능한 요약과 버전 기록
- **Google Drive:** 라이브 제어 문서, Work Claim, 원시·대형 자료, 자막, 논문과 기술 자료, 시장 데이터, 실행 산출물, 검증 증거와 snapshot
- **ChatGPT Project:** 활성 작업 채팅과 작은 hot context

공개된 정보와 자료를 자유롭게 사용한다. 작업에 사용하거나 재사용 가치가 높은 자료는 한 번 등록하고 재사용 가능하게 보존한다. 전체 영상은 영상 자체가 고유한 연구 가치를 제공할 때만 저장한다.

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

`ACTIVE_RESEARCH / revision 3`: 자료·결과·검증 재사용과 revision 기반 상태 갱신이 활성화되어 있으며, 유효한 Champion은 아직 없다.
