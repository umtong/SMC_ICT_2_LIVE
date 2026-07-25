# Control state

이 디렉터리는 작은 지속 상태의 Git mirror다. 큰 원본·로그·실험 산출물은 Drive에 두고, 여기에는 새 실행이 빠르게 판단하는 데 필요한 상태와 재사용 index만 둔다.

| 파일 | 입력 | 산출물·소비자 | 완료 기준 |
|---|---|---|---|
| `current-state.md` | 검증된 상태 변경 | 현재 revision·목표·병목·다음 작업 | 최신 revision과 다음 정확한 작업이 일치 |
| `champion.json` | 동일 조건으로 비교된 유효 결과 | Champion 또는 명시적인 없음 | state revision과 일치하고 재현 증거를 참조 |
| `work-claims.csv` | 실행 전 작업 선점 | 활성 범위·lease·branch | 완료·만료·중단 상태와 결과 ID가 기록 |
| `result-registry.jsonl` | 재사용 가능한 실험·시스템 결과 | stable result ID와 artifact/dependency fingerprint | Run Report와 artifact가 연결 |
| `validation-cache.jsonl` | 반복 사용 가능한 검증 | dependency fingerprint별 PASS/FAIL 증거 | scope·changed surface·evidence가 기록 |
| `decisions.md` | 장기적으로 유지할 결정 | 현재 운영·평가·저장 결정 | 과거 논쟁이 아니라 현재 적용 규칙만 유지 |

공통 상태를 변경하기 전에 최신 revision과 열린 PR을 다시 확인한다. 오래된 기준이면 재평가·rebase·충돌 조정 후 반영한다. 상세 계약은 `config/folder-contract.github.toml`, `config/action-contract.toml`, `docs/folder-action-contract.md`를 따른다.
