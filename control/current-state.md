# Current state

- revision: 2
- execution_mode: CONTINUOUS_PEER_PARALLEL
- fixed_epoch: none
- mandatory_coordinator: none
- valid_champion: none
- inherited_strategy_results: none
- live_order_permission: none
- repository: `umtong/SMC_ICT_2_LIVE`
- Drive root: resolved privately through `config/project.local.toml` or `00_PROJECT_BINDING`

## Active operating model

- Every project chat is a goal-directed peer worker.
- No chat waits for a coordinator, task assignment, epoch boundary, or serial handoff.
- Before substantial work, a chat checks current state, active work claims, result/validation registries, source/data registries, and relevant open PRs.
- A worker claims an unresolved high-value scope with a lease and fingerprint, works on its own branch, and writes an append-only Run Report.
- Any worker may reconcile and update shared state after checking the latest revision and resolving concurrent changes.
- Fixed E001 task assignments and pre-created lane branches from revision 1 are superseded.

## Durable data library

- Twenty user-provided Korean VTT transcripts remain registered and reusable.
- Publicly accessible information and materials may be used and retained for research.
- Materials actually used are registered once and reused; unchanged searches, downloads, chart reconstruction, transforms, backtests, and validation are not repeated.
- Full video files are retained only when they add unique research value; metadata, transcript, notes, extracted claims, and hypotheses are normally reused.

## Current objective

Pursue the top-level account-growth objective through simultaneous independent work while preventing accidental duplication and repeated whole-project validation.

## Current blockers

None. A valid Champion does not yet exist because no fresh strategy result has passed the evaluation contract.

## Next exact action

Each new chat reads `prompts/goal-worker.md`, checks `control/work-claims.csv`, `control/result-registry.jsonl`, `control/validation-cache.jsonl`, the durable source/data registries, and relevant open PRs; it then claims and executes the highest-value unresolved work. State reconciliation occurs opportunistically through revision-checked PRs and is not a prerequisite for other work.