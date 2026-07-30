# Hidden-iceberg defense executable markout fatal screen

- Claim: `CLM-20260730-HIDDEN-ICEBERG-DEFENSE-001`
- Result: `RES-20260730-HIDDEN-ICEBERG-DEFENSE-001`
- Decision: `RETIRE_EXACT_PUBLIC_HIDDEN_ICEBERG_PROXY`

## Mechanism

A hidden passive parent order is inferred only when cumulative aggressive execution exceeds the frozen q99 multiple of the initially displayed best quantity, the exact best price persists through at least 16/20 states, at least one initial display is replenished, and the executable midpoint fails to progress with the aggressor. Ask defense prescribes short; bid defense prescribes long.

## Frozen fit boundary

- 2022 eligible windows: 904540
- pooled q99 executed/display ratio: `1.939232`

## Untouched 2023-07-01 forward result

- events: 605 (ask 279, bid 326)
- 60s gross executable mean/median: `-0.6113bp` / `-0.4577bp`
- 60s after additional 24bp mean/median: `-24.6113bp` / `-24.4577bp`
- positive UTC hours at 24bp: 0
- winner-deleted 24bp mean/median: `-24.6113bp` / `-24.4577bp`

## Boundary

This is an executable source-tradability diagnostic, not an elapsed-time strategy. The prescribed fade is negative before cost, while the exact opposite sign is only about `+0.61bp` at 60 seconds and remains far below the minimum 12bp stress. No account, ML, structural lifecycle, risk/leverage or official interval opens.
