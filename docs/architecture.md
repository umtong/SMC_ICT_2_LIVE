# Architecture

## Separation of concerns

- Runtime instructions define behavior and priorities.
- TOML configuration binds a copied harness to one project.
- Google Drive holds live state, reusable sources, datasets, Run Reports, and large artifacts.
- GitHub holds versioned logic, code, work claims, provenance, manifests, decisions, and reproducible evidence.
- ChatGPT Project chats form a concurrent research mesh; chat history is not the canonical database.

## Continuous parallel research mesh

Every chat works toward the same top-level objective. No coordinator assignment or previous-chat completion is required before research begins.

Before substantial work, a chat reads current state, durable registries, open GitHub Issues/Work Claims, and active PRs. It then claims the highest-value non-overlapping task and starts immediately. When independent reproduction is useful, the claim records that the overlap is intentional.

Each execution writes only to its own branch and append-only Run Report. Shared state updates use a base revision and are reconciled periodically. Integration is a concurrent function that normalizes results, resolves conflicts, closes completed claims, and refreshes Champion/current state; it is not a sequential gate.

## Duplicate-work prevention

The system avoids repeated search and repeated rigor work through five reusable layers:

1. Source, Dataset, and Entity registries
2. Hypothesis and Experiment records
3. open Work Claims and active PRs
4. immutable Run Reports and invalidation records
5. cached data, charts, features, and comparison artifacts with checksums

Revalidation is concentrated where code, data, assumptions, evaluation contracts, or conflicting evidence materially changed.

## Reuse

`config/project.toml` contains public/non-secret bindings. The private Drive folder ID lives in ignored `config/project.local.toml` and in a private Drive binding document. `scripts/init_project.py` rewrites public bindings after this harness is copied for another project.
