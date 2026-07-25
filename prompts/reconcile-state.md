# State reconciliation prompt

최신 GitHub main 상태, Champion, 활성 Work Claim, Result Registry, Validation Cache, 폴더·행동 계약, 열린 PR과 관련 Drive Run Report를 읽는다.

각 상태 변경안을 기준 revision과 의존성 지문에 대조한다. 이미 병합된 증거와 중복 결과는 재사용하고, 독립 재현은 별도 증거로 보존한다. 데이터·비용·체결·평가 계약을 정규화한 뒤 비교한다.

산출물이 canonical folder에 있고 Run Report·Result Registry·Validation Cache와 연결되는지 확인한다. 임시 inbox, quarantine, local staging과 대체 산출물의 정리 상태를 확인한다.

근거가 충분한 변경만 반영한다. 기준 revision이 오래됐으면 현재 상태에서 결과를 재평가하고 rebase 또는 충돌을 해결한다. 검증된 PR로 상태와 Champion을 갱신하고 관련 Work Claim을 완료·갱신하며, 중요한 변경만 milestone snapshot으로 남긴다.
