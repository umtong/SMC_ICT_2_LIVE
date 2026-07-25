# SMC_ICT_2_LIVE

지속적인 트레이딩 연구, 자료·데이터 재사용, 실험 재현성과 동시 작업 충돌 방지를 위한 프로젝트 저장소다.

## 시작 순서

1. `config/project.toml`
2. `instructions/project-instructions.md`
3. `control/current-state.md`
4. `control/champion.json`
5. `control/work-claims.csv`
6. `control/result-registry.jsonl`
7. `control/validation-cache.jsonl`
8. Source·Dataset·Entity Registry
9. `docs/folder-action-contract.md`
10. `prompts/goal-worker.md`

## 작업 흐름

1. 최신 상태, Work Claim, 결과·검증·자료 레지스트리, 폴더·행동 계약과 열린 PR을 확인한다.
2. 가장 고정보가치인 미해결 범위를 선점한다.
3. 기존 자료·데이터·차트·코드·결과·검증 증거를 재사용한다.
4. 계약에 지정된 canonical folder와 action을 사용해 구현·실험·검증한다.
5. append-only Run Report를 작성하고, 저장소 변경은 작업 브랜치의 검증된 PR로 반영한다.
6. Result Registry와 Validation Cache를 갱신하거나 해당 없음의 이유를 기록한다.
7. 상태 변경 전 최신 revision과 열린 PR을 다시 확인한다.

## 폴더 유지 원칙

폴더는 목적·입력·산출물·소비자·사용 조건·완료 조건·정리 규칙이 `config/folder-contract.github.toml`, `config/folder-contract.drive.toml`, `config/action-contract.toml`에 정의된 경우에만 유지한다. 역할이 중복되면 하나의 canonical path로 통합하고, 생산자나 소비자가 없는 폴더·스크립트·템플릿은 제거하거나 역할을 다시 정의한다.

빈 폴더는 다음 네 상태 중 하나다.

- `must_not_be_empty`: 프로젝트가 정상이라면 실제 파일이 있어야 한다.
- `ready_on_demand`: 해당 종류의 첫 산출물이 생길 때 사용한다.
- `prefer_empty`: 임시 수신함이나 quarantine처럼 비어 있는 것이 정상이다.
- `prefer_absent`: 필요할 때만 생성하는 재생성 가능한 output이다.

## 저장 위치

- **GitHub:** 실행 규칙, 설정, 코드, 스키마, 스크립트, 작은 manifest, 의존성 지문, 재현 가능한 요약과 버전 기록
- **Google Drive:** 라이브 제어 문서, Work Claim, 원시·대형 자료, 시장 데이터, Run Report, 대형 산출물, 검증 증거와 snapshot
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

`ACTIVE_RESEARCH / revision 4`: 폴더·행동 계약과 구조 검증이 활성화되어 있으며, 유효한 Champion은 아직 없다.
