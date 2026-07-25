# Experiments

`03_RESEARCH/20_EXPERIMENTS`는 가설을 판단할 재현 가능한 실험 기록을 보관한다.

- 입력: hypothesis ID, immutable dataset snapshot, code commit, evaluation·cost·execution contract
- 필수 내용: 인과 정보 경계, 파라미터 탐색 범위, 재현 명령, output checksum, changed surface
- 산출물: 유효·후보·무효 결과와 증거 링크
- 완료: Result Registry와 Run Report에 연결되고 keep·modify·hold·invalidate 중 하나로 판정

대형 거래원장·모델·로그는 `04_ARTIFACTS`에 두며 실험 기록에는 stable ID와 checksum을 남긴다.
