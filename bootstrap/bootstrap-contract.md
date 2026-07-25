# New project bootstrap contract

## Inputs

- `TARGET_GITHUB_REPOSITORY`
- `TARGET_GOOGLE_DRIVE_ROOT`

## Execute

1. 대상 GitHub 저장소와 Drive 루트의 읽기·쓰기 접근을 확인한다.
2. 템플릿 저장소 `umtong/SMC_ICT_2_LIVE`의 최신 `main`에서 `bootstrap/template-manifest.toml`과 `bootstrap/drive-blueprint.json`을 읽고 사용한 commit SHA를 기록한다.
3. 대상 저장소 이름에서 프로젝트 이름과 slug ID를 파생한다. Drive 루트 이름은 폴더 메타데이터에서 읽는다.
4. 대상 저장소에 `agent/bootstrap-research-system` 브랜치를 만든다. 새 저장소가 비어 있으면 초기 commit을 만든 뒤 브랜치를 생성한다. 기존 파일이 있으면 관련 없는 파일을 삭제하거나 덮어쓰지 않고 충돌을 PR에 기록한다.
5. 템플릿 manifest의 stable files를 복사하고 reset templates를 렌더링한다. 현재 템플릿 프로젝트의 전략 결과, 순위, Work Claim, 자료·데이터 레지스트리, Run Report와 산출물을 복사하지 않는다.
6. `config/project.toml`에 대상 저장소와 프로젝트 이름을 기록한다. Drive URL·ID는 Git에서 제외되는 `config/project.local.toml`에 기록하고 공개 저장소에는 넣지 않는다.
7. Drive blueprint에 따라 폴더·문서·시트를 생성한다. 이미 같은 경로가 있으면 중복 생성하지 않고 구조와 필드를 보완한다.
8. `00_PROJECT_BINDING`에 대상 저장소, Drive 루트, 템플릿 source repository·commit·version을 기록한다.
9. GitHub와 Drive의 초기 상태를 revision 1, 전략 순위 `EMPTY`, 1위 없음, 빈 Claim·Result·Validation·Source·Dataset·Entity Registry로 맞춘다.
10. 템플릿의 검증 명령을 실행한다. 오류가 있으면 수정하고 다시 실행한다.
11. 변경을 커밋하고 draft PR을 만든다. 대상 저장소가 새로 생성된 빈 저장소이고 검증과 CI가 모두 성공하면 PR을 병합한다. 기존 내용과 충돌하면 병합하지 않고 충돌과 필요한 결정을 보고한다.
12. Drive `01_RUNS`에 bootstrap Run Report를 작성하고 GitHub branch·commit·PR·검증 결과와 정확한 다음 작업을 연결한다.
13. 완료 보고에 GitHub 저장소, Drive 루트, Project Instructions 파일, START_HERE, revision, 순위 상태, 검증 결과와 다음 정확한 작업을 포함한다.

## Completion criteria

- GitHub와 Drive binding이 서로 일치한다.
- Project Instructions는 템플릿 목표와 규칙을 그대로 사용한다.
- revision은 1이다.
- 전략 순위는 `EMPTY`이고 1위는 없다.
- 이전 프로젝트의 Result·Ranking·Claim·Source·Dataset·Run은 상속되지 않았다.
- validator, tests, context bundle build가 성공했다.
- Drive의 필수 폴더·문서·시트가 존재하고 서로 연결된다.
- 다음 연구 실행이 `00_START_HERE`만 읽고 시작할 수 있다.
