# RUN — CLAIM-20260725-ABS-FLOW-001

## Identity

- result: `RES-20260725-ABS-FLOW-001`
- base revision: 3
- re-evaluated revision: 7
- branch: `agent/absorption-flow-benchmark-r7-final-20260725`
- status: `REPORTED`

## Completed economic work

- 216 completed-five-minute candidates: zero preregistered development survivors; 2024 and 2025H1 unopened.
- 324 causal dollar-volume-clock candidates: zero development survivors and zero candidates positive in both development years at 2x costs; 2024 and 2025H1 unopened.
- Same signals replayed under base, 1.5x and 2x costs with historical funding and one global four-asset slot.

## Provisional strategy rank

`aligned_continuation|h48|z3-inf|t3|f0.1|e0.45|hold0.7|buf0.5|rr4|life720|xidiosyncratic`

| Cost | Trades | Total return | Geometric daily | PF | MDD | Top-5 share | Return without top 5 | Median hold |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ~15bp RT | 184 | 15.6276% | 0.022798% | 1.306 | -6.472% | 18.00% | 3.635% | 588m |
| ~30bp RT | 183 | 7.8715% | 0.011896% | 1.160 | -7.840% | 19.74% | -3.408% | 683m |

This hard-valid exploratory candidate is proposed as provisional rank 1 because it is materially closer to the 1% objective than the current verified first place under disclosed incomplete normalization. PR #25 candidate `021fbab613517a31ad98` remains outside ranking pending immutable-bundle verification and would outrank this result if verified.

## Validation and limitations

- finalized package: five causal/executor tests pass; three runners compile; result-ledger consistency check included;
- no sequential 2024 or 2025H1 evaluation opened;
- 2023 2x PF is about 1.026 and the combined 2x path is negative after removing top five winners;
- daily growth remains far below 1%;
- no paper/testnet/live order and no post-2025H1 data.

## Decision

Register the result once as hard-valid but economically gate-failed. Update the strategy rank provisionally after CI and registry reconciliation; do not grant research priority or live permission. Retire ordinary five-minute and dollar-clock absorption-family threshold search under unchanged dependencies.
