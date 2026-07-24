# SMC_ICT_2_LIVE

Configuration-driven research operating system for concurrent ChatGPT Project chats, reproducible trading research, and durable source/data reuse.

## Purpose

This repository is the canonical, versioned project layer. Google Drive is the high-frequency private data and live-state layer. Every ChatGPT Project chat is an independent goal worker that reads the same state, claims a high-value unresolved scope, reuses existing evidence, and continues directly toward the project objective.

The repository starts from a clean state. It does not inherit strategy code or state from `SMC-trading-system` unless a future task explicitly imports a verified artifact.

## Read order

1. `config/project.toml`
2. `instructions/project-instructions.md`
3. `control/current-state.md`
4. `control/champion.json`
5. `control/work-claims.csv`
6. `control/result-registry.jsonl`
7. the Source/Dataset/Entity registries
8. `prompts/goal-worker.md`

## Execution model

- All chats are peer workers pursuing the same top-level objective.
- There is no mandatory coordinator, fixed epoch gate, or serial handoff.
- Workers avoid accidental duplicate work through leased scope fingerprints, registries, open-PR checks, and result/dependency fingerprints.
- Intentional independent replication is allowed only when its distinct value is recorded.
- Any worker may reconcile and update shared state through optimistic revision checks and a validated PR.
- Unchanged searches, charts, data transforms, backtests, and audits are reused rather than rebuilt.

## Storage split

- **GitHub:** instructions, configuration, code, schemas, scripts, small manifests, dependency fingerprints, reproducible summaries, and version history.
- **Google Drive:** live control documents, work claims, large/raw research-used sources, transcripts, papers and technical material, market datasets, run artifacts, validation evidence, and snapshots.
- **ChatGPT Project:** active chats and a small hot context set; it is not the sole source of truth.

Publicly accessible information and materials may be used and retained for research. Materials actually used are registered once and reused. Full video files are stored only when they add unique research value; transcripts, metadata, notes, claims, and hypotheses are normally sufficient.

## Quick checks

```bash
python scripts/validate_project.py
python scripts/register_source.py --help
python scripts/claim_work.py --help
python scripts/new_run.py --help
python scripts/build_context_bundle.py
```

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

`ACTIVE_RESEARCH / revision 2 / CONTINUOUS_PEER_PARALLEL`: the control plane and durable data library are active. Twenty initial transcripts are registered, fixed E001 assignments are superseded by leased work claims, and no Champion is asserted until a fresh strategy result passes the evaluation contract.