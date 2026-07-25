# Google Drive layout

```text
<PROJECT_ROOT>/
├─ 00_START_HERE
├─ 00_CONTROL/
│  ├─ 00_PROJECT_BINDING
│  ├─ 01_PROJECT_STATE
│  ├─ 02_CHAMPION
│  ├─ 03_WORK_CLAIMS
│  ├─ 04_DECISION_LOG
│  ├─ 05_EVALUATION_CONTRACT
│  ├─ 06_GOAL_WORKER_PROMPT
│  ├─ 07_SYSTEM_MAP
│  ├─ 08_RESULT_REGISTRY
│  ├─ 09_VALIDATION_CACHE
│  ├─ 10_STATE_RECONCILE_PROMPT
│  └─ 11_FOLDER_ACTION_CONTRACT
├─ 01_RUNS/
├─ 02_DATA/
│  ├─ 00_INBOX/
│  ├─ 10_YOUTUBE/
│  │  ├─ 00_RAW_TRANSCRIPTS/
│  │  ├─ 10_SOURCE_NOTES/
│  │  └─ 20_EXTRACTED_CLAIMS/
│  ├─ 20_PAPERS/
│  ├─ 30_TRADERS_AND_FUNDS/
│  ├─ 40_COMPETITIONS_AND_CASES/
│  ├─ 50_EXCHANGES_BROKERS_APIS/
│  ├─ 60_CODE_AND_REPOS/
│  ├─ 70_MARKET_AND_REFERENCE_DATA/
│  ├─ 80_PROCESSED_AND_EXTRACTED/
│  ├─ 90_MANIFESTS_AND_INDEXES/
│  └─ 99_DUPLICATES_AND_QUARANTINE/
├─ 03_RESEARCH/
│  ├─ 10_HYPOTHESES/
│  ├─ 20_EXPERIMENTS/
│  ├─ 30_REPORTS/
│  └─ 40_INVALIDATED_AND_REJECTED/
├─ 04_ARTIFACTS/
├─ 05_SNAPSHOTS/
└─ 90_ARCHIVE/
```

## 경계 규칙

- `02_DATA`는 출처·데이터·결정론적 가공물을 보관한다.
- `03_RESEARCH`는 가설·실험·판단·무효 지식을 보관한다.
- 가설의 canonical 위치는 `03_RESEARCH/10_HYPOTHESES` 한 곳이다.
- `01_RUNS`는 실행 보고서, `04_ARTIFACTS`는 대형 실행 산출물이다.
- `05_SNAPSHOTS`는 중요한 상태의 완전한 복구점, `90_ARCHIVE`는 비활성 자료 보관소다.
- `00_INBOX`와 `99_DUPLICATES_AND_QUARANTINE`은 비어 있는 것이 정상이며 장기 저장소로 사용하지 않는다.

각 폴더의 입력·산출물·사용·완료·정리 규칙은 `config/folder-contract.drive.toml`과 `docs/folder-action-contract.md`를 따른다.
