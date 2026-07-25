# Run reports

각 실행은 목표 달성 또는 시간제한 시 고유한 append-only 보고서를 남긴다.

`RUN__<worker_id>__<claim_id>__<timestamp>.md`

## 입력

- Work Claim과 base revision
- 재사용한 source·dataset·result·validation ID
- 코드 commit, 평가·비용·체결 계약
- 실제 수행 작업과 생성 산출물

## 필수 산출물

- 완료 작업과 핵심 수치
- 실패·무효와 원인
- changed-surface validation
- branch·commit·PR·Drive artifact 링크
- Work Claim disposition
- Result Registry·Validation Cache 반영 여부
- 다음 정확한 작업과 판정 조건

## 완료·보존

보고서는 덮어쓰지 않는다. 정정이 필요하면 기존 보고서를 참조하는 새 보고서를 만들고 supersede 관계를 기록한다. 큰 증거 파일은 `04_ARTIFACTS`에 두고 보고서에서는 ID와 링크만 남긴다.
