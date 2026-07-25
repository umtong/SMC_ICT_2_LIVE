# Reusable two-input project bootstrap

이 부트스트랩은 동일한 SMC/ICT 연구 목표와 운영구조를 새 GitHub 저장소와 새 Google Drive 루트에 구성한다.

## 필요한 입력

1. `TARGET_GITHUB_REPOSITORY`: `owner/name` 또는 GitHub 저장소 URL
2. `TARGET_GOOGLE_DRIVE_ROOT`: Google Drive 폴더 URL 또는 폴더 ID

프로젝트 이름과 ID는 대상 GitHub 저장소 이름에서 파생한다. Drive 폴더 이름은 Drive 메타데이터에서 읽고, 읽을 수 없으면 프로젝트 이름을 사용한다.

## 사용 방법

새 프로젝트의 ChatGPT Project 채팅에 `prompts/bootstrap-new-project.md`의 전체 내용을 넣고 두 입력값만 교체한다.

로컬 또는 코드 실행 환경이 있으면 다음 명령으로 저장소 파일을 생성할 수 있다.

```bash
python scripts/instantiate_project.py \
  --github-repository owner/NEW_PROJECT \
  --drive-root-url 'https://drive.google.com/drive/folders/DRIVE_ID' \
  --output /tmp/NEW_PROJECT
```

생성된 저장소는 revision 1, 빈 전략 순위, 빈 Work Claim·Result·Validation·자료 레지스트리로 시작한다. 현재 SMC_ICT_2_LIVE의 전략 결과, 순위, 데이터, 실행 보고서와 상태는 상속하지 않는다.

## 정본

- 저장소 파일 복제·초기화 규칙: `bootstrap/template-manifest.toml`
- Drive 폴더·문서·시트 구조: `bootstrap/drive-blueprint.json`
- 새 AI 실행 명령: `bootstrap/bootstrap-contract.md`
- Drive 문서 초기 내용: `bootstrap/drive-templates/`
