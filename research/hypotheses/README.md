# Hypotheses

`03_RESEARCH/10_HYPOTHESES`는 프로젝트의 반증 가능한 가설을 보관하는 canonical 위치다.

- 입력: 원래 추론 또는 등록된 source/claim ID
- 필수 내용: 메커니즘, 조건, 인과 정보 경계, 정량 예측, 최소 실험, 성공·실패 조건
- 산출물: stable hypothesis ID와 실험 후보
- 완료: `20_EXPERIMENTS`의 실험 또는 `40_INVALIDATED_AND_REJECTED`의 기각 기록에 연결

구현 파라미터와 포지션 사이징을 메커니즘 자체와 분리한다. `02_DATA`의 출처별 폴더에는 가설 파일을 중복 저장하지 않는다.
