# Architecture

## Separation of concerns

- Runtime instructions define behavior.
- TOML configuration binds a copied harness to one project.
- Drive holds live private state and large durable data.
- GitHub holds versioned logic, provenance, manifests, and reproducible evidence.
- ChatGPT chats execute concurrent lanes; they are not the canonical database.

## Concurrency model

Research lanes are multi-writer only for append-only run reports and their own branches. Shared state has one writer: the coordinator. Every run carries `epoch_id`, `lane_id`, `task_id`, and `base_revision` to detect stale results.

## Reuse

`config/project.toml` contains public/non-secret bindings. The private Drive folder ID lives in ignored `config/project.local.toml` and in a private Drive `00_PROJECT_BINDING` document. `scripts/init_project.py` rewrites the public binding after this repository is copied for another project.
