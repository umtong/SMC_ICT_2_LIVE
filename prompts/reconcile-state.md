# State reconciliation prompt

최신 GitHub main의 Project State와 Champion을 읽고, 변경하려는 내용과 관련된 Work Claim, Result Registry, Validation Cache, 열린 PR과 Drive Run Report만 검색한다.

Champion, 핵심 병목, 다음 정확한 작업, 평가 계약 또는 재사용 가능한 공통 자산을 바꾸는 근거가 있을 때만 상태를 갱신한다. 사소한 진행 상황이나 임시 분석은 공통 상태에 병합하지 않는다.

각 상태 변경안을 기준 revision과 의존성 지문에 대조한다. 이미 병합된 증거와 중복 결과는 재사용하고, 데이터·비용·체결·평가 계약을 정규화한 뒤 비교한다.

근거가 충분한 변경만 검증된 PR로 반영한다. 기준 revision이 오래됐으면 현재 상태에서 결과를 재평가하고 rebase 또는 충돌을 해결한다. 관련 Work Claim과 Result Registry를 갱신하고, Champion·평가 계약·핵심 데이터가 바뀐 경우에만 milestone snapshot을 남긴다.
