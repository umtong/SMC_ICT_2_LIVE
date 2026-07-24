# Durable data library

The data library prevents repeated searching, re-downloading, and re-interpreting the same material.

## Source classes

- YouTube videos and transcripts
- papers and technical reports
- day traders, funds, public performance cases, and competitions
- exchange, broker, API, fee, and market-data documentation
- code repositories and implementations
- market and reference datasets

## Intake contract

1. Search the registry before searching externally.
2. Canonicalize the URL and compute SHA-256 for any local file.
3. If the canonical URL or hash already exists, reuse the existing source or place a conflicting duplicate in quarantine.
4. Store raw bytes in Drive when permitted; keep raw files immutable.
5. Record metadata and relative Drive path in `data/catalog/source-registry.jsonl`.
6. Extract claims and hypotheses into processed/research records; do not treat external claims as verified results.
7. Cite provenance in every downstream experiment.

Git intentionally ignores `data/raw`, `data/cache`, and `data/downloads` except marker files. Large files belong in Drive or another configured store.
