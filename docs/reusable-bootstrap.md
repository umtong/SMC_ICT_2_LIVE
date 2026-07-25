# Reusable project bootstrap

새 프로젝트에서는 목표와 운영규칙을 다시 설계하지 않는다. 사용자는 새 GitHub 저장소와 새 Google Drive 루트만 제공하고, 부트스트랩은 프로젝트 이름·ID를 파생해 동일한 구조를 생성한다.

## AI 사용

`prompts/bootstrap-new-project.md`의 두 값을 교체하고 새 프로젝트 채팅에서 실행한다.

## 로컬 사용

```bash
python scripts/instantiate_project.py \
  --github-repository owner/NEW_PROJECT \
  --drive-root-url 'https://drive.google.com/drive/folders/DRIVE_ID' \
  --output /tmp/NEW_PROJECT
```

선택 입력:

- `--project-name`: 저장소 이름과 다른 표시 이름이 필요한 경우
- `--project-id`: 자동 slug 대신 다른 ID가 필요한 경우
- `--drive-root-name`: Drive 메타데이터를 읽을 수 없는 로컬 실행에서 사용
- `--allow-existing`: 비어 있지 않은 대상 디렉터리에 병합할 때 사용

## 초기 상태

- revision 1
- phase `ACTIVE_RESEARCH`
- 전략 순위 `EMPTY`
- 1위 없음
- Work Claim·Result·Validation·Source·Dataset·Entity Registry 비어 있음
- 기존 프로젝트의 전략 결과·순위·자료·Run Report·산출물 상속 없음

## Drive

새 AI는 `bootstrap/drive-blueprint.json`을 사용해 폴더, 문서와 시트를 생성한다. Drive URL과 ID는 `config/project.local.toml`과 Drive `00_PROJECT_BINDING`에만 기록하고 공개 저장소에는 커밋하지 않는다.

## 완료 판정

- `python scripts/validate_project.py`
- `python -m pytest`
- `python scripts/build_context_bundle.py`
- GitHub revision 1 상태와 Drive revision 1 상태 일치
- bootstrap Run Report 존재
- `00_START_HERE`에서 첫 연구 작업을 바로 시작할 수 있음
