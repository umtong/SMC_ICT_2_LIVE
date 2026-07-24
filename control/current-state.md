# Current state

- revision: 2
- epoch: CONTINUOUS
- phase: ACTIVE_PARALLEL_RESEARCH
- valid_champion: none
- inherited_strategy_results: none
- live_order_permission: none
- repository: `umtong/SMC_ICT_2_LIVE`
- Drive root: resolved privately through `config/project.local.toml` or `00_PROJECT_BINDING`

## Active operating model

- All project chats work toward the same top-level objective concurrently.
- Research does not wait for coordinator assignment, another chat, or an epoch boundary.
- Each chat reads current state, registries, open Work Claims, active PRs, and reusable artifacts; then it claims the highest-value non-duplicate task and starts immediately.
- An intentional independent reproduction is allowed when marked in its Work Claim.
- Integration periodically reconciles results and updates shared state; it is not a research gate.

## Durable reuse

- Twenty user-provided Korean VTT transcripts are stored and registered with canonical URLs and checksums.
- Public information and materials may be used. Materials used by the strategy or likely to be reused are stored and registered without a separate storage-permission investigation.
- Existing data, charts, code, experiments, and invalidation records are reused. Equivalent search, chart reconstruction, and rigor checks are not repeated unless a material input or conflicting result changed.

## Current objective

Run continuous parallel research across alpha discovery, source/data enrichment, execution, portfolio construction, and rapid validity checks. Each chat may cross its priority area when another bottleneck has higher expected value.

## Current blockers

None. A valid Champion does not yet exist because no fresh strategy result has passed the project evaluation contract.

## Next exact action

Every active project chat checks open GitHub Issues/Work Claims and durable registries, creates a non-duplicate Work Claim, and immediately executes the highest-value task until goal completion or time limit. Integration may run at the same time and updates shared state when supported evidence is ready.
