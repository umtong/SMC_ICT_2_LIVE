# Operating playbook

1. Coordinator reads current state and registry, then creates non-overlapping tasks.
2. Each lane creates a branch only if repository files will change.
3. Before external search, the lane queries the source/entity registry.
4. New durable sources are ingested once and registered; raw permitted files go to Drive.
5. The lane performs executable work, commits reproducible changes, and writes an append-only run report.
6. Coordinator normalizes conditions, rejects invalid/stale results, merges supported PRs, updates Champion/state, and creates the next epoch.
7. At material milestones, build a context bundle and Drive snapshot.
