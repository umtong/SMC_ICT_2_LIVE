# State reconciliation prompt

최신 GitHub main의 Project State와 Champion을 읽고, 변경하려는 내용과 관련된 Work Claim, Result Registry, Validation Cache, 열린 PR과 Drive Run Report만 검색한다.

Champion은 최종 목표 달성이나 실사용 승인과 분리된 현재 최우수 hard-valid 전략 또는 포트폴리오 후보를 가리키는 순위 포인터다. 판정 가능한 새 전략 결과가 있으면 현재 Champion과 비교하고, 목표 미달이나 낮은 검증 단계만을 이유로 Champion 선정을 미루지 않는다. 후보가 더 우수하면 검증 단계, 목표 격차, 비용·체결 조건, 비교 불확실성과 취약점을 기록하여 Champion이 가리키는 result ID를 갱신한다. 부분 구성요소는 component leader로 별도 관리한다.

Champion 지위는 연구 우선순위나 추가 보호·검증 절차를 만들지 않는다. Champion, 핵심 병목, 다음 정확한 작업, 평가 계약 또는 재사용 가능한 공통 자산을 바꾸는 근거가 있을 때만 상태를 갱신한다. 사소한 진행 상황이나 임시 분석은 공통 상태에 병합하지 않는다.

각 상태 변경안을 기준 revision과 의존성 지문에 대조한다. 이미 병합된 증거와 중복 결과는 재사용하고, 데이터·비용·체결·평가 계약을 가능한 범위에서 정규화한 뒤 비교한다. 완전한 정규화가 불가능하면 비교 신뢰도를 표시하고 provisional research Champion을 유지한다.

모든 판정 가능한 결과는 Champion 여부와 무관하게 일반 결과 기록과 버전관리에서 재사용 가능해야 한다. Champion 교체 또는 접근 전환을 이유로 이미 기록된 이전 결과를 다시 백업·복제·재검증하지 않는다.

근거가 충분한 변경만 검증된 PR로 반영한다. 기준 revision이 오래됐으면 현재 상태에서 결과를 재평가하고 rebase 또는 충돌을 해결한다. 관련 Work Claim과 Result Registry를 갱신하고, 평가 계약·핵심 데이터·운영 구조처럼 복구 가치가 큰 변경에만 milestone snapshot을 남긴다.
