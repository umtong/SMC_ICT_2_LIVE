# Google Drive layout

```text
<PROJECT_ROOT>/
├─ 00_CONTROL/
├─ 01_RUNS/
├─ 02_DATA/
│  ├─ 00_INBOX/
│  ├─ 10_YOUTUBE/
│  │  ├─ 00_RAW_TRANSCRIPTS/
│  │  ├─ 10_SOURCE_NOTES/
│  │  ├─ 20_EXTRACTED_CLAIMS/
│  │  └─ 30_HYPOTHESES/
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
├─ 04_ARTIFACTS/
├─ 05_SNAPSHOTS/
├─ 90_ARCHIVE/
└─ 99_LEGACY_BOOTSTRAP_<DATE>/
```

Only the coordinator edits shared control documents. Research lanes create unique run reports and source-intake batches.
