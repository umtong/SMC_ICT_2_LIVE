# Agent operating rules

1. Read `config/project.toml`, project instructions, current state, durable registries, open Work Claims, and active PRs before starting.
2. All chats pursue the same project objective concurrently. Do not wait for a coordinator assignment or another chat to finish when a high-value non-duplicate task is available.
3. Claim work before substantial execution by creating a GitHub Issue or Drive Active Work entry with objective, scope, base revision, inputs, and expected artifacts. An intentional independent reproduction must be marked as such.
4. Reuse registered sources, datasets, charts, code, experiments, and invalidation records. Do not repeat equivalent search, chart reconstruction, or validation unless a material input, assumption, implementation, or conflicting result changed.
5. Public information and materials may be used. Store materials used by the project or likely to be reused without a separate storage-permission investigation. Large raw files go to Drive; Git stores manifests, checksums, transforms, small outputs, and decisions.
6. Each execution uses its own branch and append-only Run Report. Do not overwrite another execution's branch or report.
7. Shared state changes are proposed through revision-checked patches or PRs. Integration is periodic reconciliation, not a gate that authorizes research to start.
8. Do not silently compare results produced with different data, cost, execution, or evaluation contracts.
9. Invalid results are preserved with an invalidation reason; they are not quietly deleted from history.
10. Keep runtime instructions stable, current state concise, and historical/raw material outside the hot context bundle.
11. `main` changes arrive through a reviewed pull request with successful validation. Never force push shared branches.
12. Do not put secrets, private Drive URLs, credentials, account identifiers, or personal data in the public repository.
13. Model names, subscription names, historical debate, and rationale for past instructions do not belong in runtime rules.
