# Parallel research mesh

## Goal-directed concurrency

All project chats are active researchers, not steps in a queue. A chat does not wait for a coordinator, a previous lane, or an epoch boundary when executable high-value work exists.

## Work Claim protocol

Before substantial work, create a GitHub Issue titled:

`[WORK] <work_id> — <concise objective>`

The issue records:

- work ID and chat/lane
- base state revision
- objective and scope
- existing registry entries, experiments, PRs, and claims checked
- datasets and source IDs
- expected artifacts and decision condition
- whether overlap is an intentional independent reproduction

If an open claim already covers the same scope, reuse its outputs, collaborate through the issue/PR, or move to another bottleneck. Do not silently repeat the work.

## Execution isolation

- Use one branch per Work Claim.
- Use one append-only Run Report per execution.
- Link Issue → branch → commits → PR → Run Report → data/artifact paths.
- Do not overwrite another chat's branch, report, or results.

## Shared state

Research results are not blocked on shared-state updates. Completed work proposes a state patch. An integration chat periodically compares patches under their data, cost, execution, and evaluation contracts, then updates Champion/current state with revision checks.

Multiple integration chats may analyze results concurrently, but only a revision-compatible state PR is merged. A stale integration result is rebased or re-evaluated rather than silently applied.

## Reuse before repetition

Before web search, data download, chart construction, or audit, check:

1. open Work Claims and active PRs
2. Source, Dataset, and Entity registries
3. Hypothesis and Experiment records
4. cached charts, features, data snapshots, and comparison reports
5. invalidation and failure records

Repeat work only when independent reproduction has explicit value or a material change makes prior evidence insufficient.
