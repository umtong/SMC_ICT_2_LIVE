# Durable data library

The data library prevents repeated searching, downloading, chart reconstruction, and reinterpretation of the same material.

## Source classes

- YouTube videos, transcripts, and creator/channel metadata
- papers and technical reports
- day traders, funds, public performance cases, and competitions
- exchange, broker, API, fee, and market-data documentation
- code repositories and implementations
- market and reference datasets
- generated charts, features, experiment outputs, and invalidated approaches

## Intake contract

1. Search Source, Dataset, Entity, Hypothesis, Experiment, and open Work Claim registries before external search.
2. Reuse an existing source, dataset, chart, code path, experiment, or failure record when it already answers the need.
3. Canonicalize the URL and compute SHA-256 for stored files.
4. If the canonical URL or hash already exists, reuse it or place a conflicting duplicate in quarantine.
5. Public information and materials may be used for project research. Store materials actually used by a strategy or validation task, and materials with clear reuse value, without a separate storage-permission investigation.
6. Full video files are not stored by default unless the video bytes are directly needed. Prefer transcripts, metadata, source notes, claims, and hypotheses. Do not spend research time debating storage when the useful representation is obvious.
7. Keep raw files immutable, version processed outputs, and record metadata plus the relative Drive path in the appropriate registry.
8. Extract claims and hypotheses into processed research records; external claims remain hypotheses until reproduced in our environment.
9. Cite source IDs and dataset snapshot IDs in downstream experiments.

Git intentionally ignores raw and large files except marker files. Google Drive is the durable data layer; GitHub stores manifests, checksums, transformations, small reproducible outputs, and decisions.
