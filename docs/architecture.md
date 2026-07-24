# Architecture

## Separation of concerns

- Runtime instructions define behavior.
- TOML configuration binds a copied harness to one project.
- Google Drive holds live private state, append-only Run Reports, registries, and large durable data.
- GitHub holds versioned logic, provenance, manifests, dependency fingerprints, reproducible evidence, and durable state.
- ChatGPT Project chats are concurrent goal workers; chat history is not the canonical database.

## Peer-parallel concurrency

There is no mandatory coordinator or sequential epoch gate. Every chat reads the latest state, active work claims, result registries, source/data registries, and relevant open PRs, then claims the highest-value unclaimed scope it can execute.

A claim records a worker ID, objective/scope fingerprint, base revision, lease, branch, and overlap reason when intentional replication is valuable. Accidental overlap is avoided; deliberate replication is allowed only when it adds distinct evidence.

Each worker writes an append-only Run Report and uses its own GitHub branch. Any worker may update shared state or Champion after re-reading the latest revision and reconciling concurrent changes. GitHub PR conflicts and revision checks provide optimistic concurrency. A reconciliation chat may be used for convenience but is never a prerequisite for progress.

## Reuse and validation cache

Sources, datasets, charts, feature outputs, code artifacts, results, and validation evidence are addressed by stable IDs and dependency fingerprints. Unchanged dependencies reuse prior artifacts and attestations. Validation targets changed code/data/assumptions and new hypothesis risk rather than rebuilding or re-auditing the whole project.

## Reuse for other projects

`config/project.toml` contains public/non-secret bindings. The private Drive folder ID lives in ignored `config/project.local.toml` and in a private Drive `00_PROJECT_BINDING` document. `scripts/init_project.py` rewrites the public binding after this repository is copied for another project.