# Folder and action contract audit

- claim_id: CLAIM-20260725-FOLDER-ACTION-CONTRACT
- base_revision: 3
- status: REPORTED
- started_at: 2026-07-25T15:39:41+09:00
- ended_at: 2026-07-25T16:24:50+09:00

## Objective

각 지속 폴더와 반복 행동의 존재 이유, 입력, 산출물, 소비자, 사용 조건, 완료와 정리 규칙을 정의하고 중복·고아 구조를 제거한다.

## Audit findings

- `00_CONTROL`은 실제 사용 중이었지만 Result Registry와 Validation Cache는 비어 있었다.
- `02_DATA/10_YOUTUBE/30_HYPOTHESES`가 `03_RESEARCH/10_HYPOTHESES`와 역할이 겹쳤다.
- 일부 빈 폴더에는 ready-on-demand·prefer-empty 같은 의도된 상태가 없었다.
- PR과 Work Claim은 canonical output, registry update, cleanup decision을 요구하지 않았다.
- 여러 README는 목적만 적고 입력·소비자·완료·보존 규칙이 없었다.

## Completed

- 18개 GitHub/local 폴더, 25개 Drive 폴더와 13개 반복 행동의 machine-readable 계약을 추가했다.
- 사람이 읽는 폴더·행동 참조 문서를 추가했다.
- Work Claim과 PR 템플릿을 추가했다.
- 실행 규칙과 prompts를 canonical path와 lifecycle에 연결했다.
- 필수 필드, 고유 canonical role, 빈 폴더 정책, 필수 행동, 중복 가설 경로와 PR completion marker를 CI에서 검사한다.
- Drive 중복 폴더와 legacy 위치 정리, revision 4 control update를 준비했다.

## Reused evidence

- revision 3 repository structure and state
- Drive root/control/data/research/artifact/snapshot/archive inventory
- Source Registry의 20개 transcript record
- 열린 PR #10·#11과 활성 Work Claim

## Result registration

- result_id: RESULT-20260725-FOLDER-ACTION-CONTRACT
- artifact_fingerprint: 60ea666239bf9df8326652d3c27c5577c9f4005ad0f87e3196e57316afbd39a8
- dependency_fingerprint: 42fc81b32217e134c8a8f24a01a5571371bac499ee9049a522067ffc17fd06f3
- validation_attestation: VAL-20260725-FOLDER-ACTION-CONTRACT

## GitHub

- branch: `agent/folder-action-contract-audit`
- issue: https://github.com/umtong/SMC_ICT_2_LIVE/issues/12
- pull request: pending

## Drive

- folder contract document: pending
- revision 4 snapshot: pending

## Decision

Keep. 이 계약은 고아 폴더, 중복 역할, 소비자 없는 산출물, 사용되지 않는 registry와 일관되지 않은 완료 행동을 직접 차단한다.

## Next exact action

Repository CI를 실행하고 Drive 중복 폴더를 정리한 뒤 control documents와 registries를 revision 4로 갱신하고 병합한다.
