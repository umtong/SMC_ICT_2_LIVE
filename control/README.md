# Control state

이 디렉터리는 지속 상태의 Git mirror다. Google Drive는 라이브 문서와 대형 자료를 보관한다.

- `current-state.md`: 현재 상태와 다음 정확한 작업
- `champion.json`: 검증된 Champion 또는 명시적인 없음 상태
- `work-claims.csv`: 활성 작업 범위와 lease
- `result-registry.jsonl`: 산출물·의존성 지문으로 식별한 재사용 가능한 결과
- `validation-cache.jsonl`: 의존성이 바뀌지 않은 검증 증거
- `decisions.md`: 장기 결정 기록

작업 결과는 고유 Run Report와 작업 브랜치에 기록한다. 공통 상태를 변경하기 전에 최신 revision과 열린 PR을 다시 확인하고, 오래된 기준이면 재평가·rebase·충돌 조정 후 반영한다.
