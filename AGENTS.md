# Agent operating rules

1. Read `config/project.toml`, project instructions, and current state before changing anything.
2. Never place secrets, private Drive URLs, account identifiers, credentials, or restricted data in this public repository.
3. Raw source files and large datasets go to the configured Drive folders. Git stores metadata, checksums, relative paths, and reproducible transforms.
4. Every research lane uses its own branch and append-only run report. Only the coordinator updates shared state and Champion records.
5. Do not silently compare results produced with different data, cost, execution, or evaluation contracts.
6. New durable external sources must be registered before repeated use. Check canonical URL and SHA-256 duplicates first.
7. Invalid results are preserved with an invalidation reason; they are not quietly deleted from history.
8. Keep instructions stable, current state concise, and raw historical material outside the hot context bundle.
9. `main` changes should arrive through a reviewed pull request with successful validation.
10. Model names, subscription names, and rationale for past instructions do not belong in runtime rules.
