# SMC_ICT_2_LIVE

Configuration-driven research operating system for concurrent ChatGPT Project chats, reproducible trading research, and durable source/data reuse.

## Purpose

This repository is the canonical, versioned project layer. Google Drive is the high-frequency private data and live-state layer. ChatGPT Project chats are execution lanes that read the same binding, work independently, and return append-only reports for coordinator merge.

The repository starts from a clean state. It does not inherit strategy code or state from `SMC-trading-system` unless a future task explicitly imports a verified artifact.

## Read order

1. `config/project.toml`
2. `instructions/project-instructions.md`
3. `control/current-state.md`
4. `control/champion.json`
5. `control/task-board.csv`
6. the assigned prompt under `prompts/`

## Storage split

- **GitHub:** instructions, configuration, code, schemas, scripts, small manifests, reproducible summaries, version history.
- **Google Drive:** live control documents, large/raw source files, transcripts, PDFs where storage is permitted, market datasets, run artifacts, and snapshots.
- **ChatGPT Project:** active chats and a small hot context set; it is not the sole source of truth.

## Quick checks

```bash
python scripts/validate_project.py
python scripts/register_source.py --help
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

`BOOTSTRAP`: storage and control-plane structure are being initialized. No Champion is asserted and no strategy result is inherited.
