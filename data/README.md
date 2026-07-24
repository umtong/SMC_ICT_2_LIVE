# Durable data library

The data library prevents repeated searching, re-downloading, re-interpreting, chart reconstruction, and duplicate hypothesis extraction.

## Source classes

- YouTube videos and transcripts
- papers and technical reports
- day traders, funds, public performance cases, and competitions
- exchange, broker, API, fee, and market-data documentation
- code repositories and implementations
- market and reference datasets

## Intake contract

1. Search Source, Dataset, Entity, Result, and active Work Claim registries before external search.
2. Canonicalize the URL and compute SHA-256 for any stored file.
3. If the canonical URL or hash already exists, reuse the existing source or place a conflicting duplicate in quarantine.
4. Publicly accessible information and materials may be used and retained for research; do not create a separate permission-classification workflow.
5. Store material actually used in Drive and keep raw files immutable. Full videos are stored only when they add unique research value.
6. Record metadata and relative Drive path in `data/catalog/source-registry.jsonl`.
7. Extract claims and hypotheses into processed/research records; do not treat external claims as verified results.
8. Record source IDs and dependency fingerprints in every downstream experiment and result.
9. Reuse unchanged processed outputs and validation evidence rather than rebuilding them.

Git intentionally ignores `data/raw`, `data/cache`, and `data/downloads` except marker files. Large files belong in Drive or another configured store.