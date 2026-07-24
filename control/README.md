# Control state

This directory is the small Git mirror of durable project state. Google Drive is the live collaborative and large-data surface. There is no mandatory coordinator; every worker uses optimistic revision checks and validated PRs when updating shared state.

- `current-state.md`: concise current state and next exact action.
- `champion.json`: current validated Champion or an explicit null state.
- `work-claims.csv`: leased scope claims that prevent accidental duplicate work.
- `result-registry.jsonl`: reusable results identified by artifact and dependency fingerprints.
- `validation-cache.jsonl`: versioned attestations for unchanged validity checks.
- `decisions.md`: append-only durable decisions.

Workers write unique Run Reports and use their own branches. Before changing shared state, re-read the latest revision and open PRs. If the base revision is stale, reconcile rather than overwrite.