# SMC_ICT_2_LIVE

Configuration-driven research operating system for concurrent ChatGPT Project chats, reproducible trading research, and durable source/data reuse.

## Purpose

This repository is the canonical, versioned project layer. Google Drive is the high-frequency data and live-state layer. ChatGPT Project chats form a continuous goal-directed research mesh: each chat reads the same state, claims non-duplicate high-value work, executes immediately, and publishes append-only evidence for periodic integration.

The repository starts from a clean state. It does not inherit strategy code or state from `SMC-trading-system` unless a future task explicitly imports a verified artifact.

## Read order

1. `config/project.toml`
2. `instructions/project-instructions.md`
3. `control/current-state.md`
4. `control/champion.json`
5. open GitHub Issues/Work Claims and active PRs
6. durable Source/Dataset/Entity/Hypothesis/Experiment registries
7. the most relevant prompt under `prompts/`

## Storage split

- **GitHub:** instructions, configuration, code, schemas, scripts, work claims, small manifests, checksums, reproducible summaries, decisions, and version history.
- **Google Drive:** live control documents, public research materials used by the project, transcripts, papers, market datasets, cached charts/features, run artifacts, and snapshots.
- **ChatGPT Project:** active concurrent chats and a small hot context set; it is not the sole source of truth.

Public information and materials may be used. Store what the strategy or validation actually uses and what is likely to be reused. Full video files are not stored by default when transcripts, metadata, or notes are sufficient; do not turn storage decisions into a research task.

## Quick checks

```bash
python scripts/validate_project.py
python scripts/register_source.py --help
python scripts/new_run.py --help
python scripts/build_context_bundle.py
```

## Concurrent work

Before substantial work, create a GitHub Issue with the `[WORK]` prefix or an equivalent Drive Active Work entry. Record objective, scope, base revision, inputs, expected artifacts, and whether any overlap is an intentional independent reproduction. Link the issue from the branch, PR, and Run Report.

Integration updates shared state periodically but does not assign permission to research. Every chat continues toward the project objective until goal completion or its time limit.

## Reuse for another project

Copy this repository or use it as a template, then run:

```bash
python scripts/init_project.py \
  --project-id new-project \
  --project-name NEW_PROJECT \
  --github-repository owner/NEW_PROJECT \
  --drive-root-name NEW_PROJECT
```

The command rewrites only project-specific bindings. Put the private Google Drive folder ID in `config/project.local.toml`, which is intentionally ignored by Git.

## Current status

`ACTIVE_PARALLEL_RESEARCH / revision 2`: the durable data library and continuous parallel research mesh are active. Twenty initial transcripts are registered, no Champion is asserted, and all chats may immediately pursue the highest-value non-duplicate work while integration proceeds independently.
