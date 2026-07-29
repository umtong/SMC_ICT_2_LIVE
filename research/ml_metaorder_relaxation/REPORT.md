# ML metaorder impact-relaxation lifecycle — decision report

**Result:** `RES-20260730-ML-METAORDER-RELAXATION-001`  
**Claim:** `CLM-20260730-ML-METAORDER-RELAXATION-001` / issue #461  
**Decision:** **ECONOMIC FAIL**; 2023 and official 2024–2026 remained unopened.

## Economic mechanism

The route treated a persistent 30-second aggressive-flow run as a possible venue-wide metaorder. It waited for two completed five-second states showing same-side flow cessation, then compared two causal actions: continuation of a permanent-impact repricing or relaxation toward the two-thirds retained-impact point. Flat was always available.

The pilot reused only registered Bybit `MICROBAR-SPARSE500-V5` months for BTCUSDT and ETHUSDT. Decisions used completed states, the fixed 500 ms delay and the first later observed trade. One global slot, structural barriers, exact funding, 12/18/24 bp cost stress, fixed 0.5% NAV planned loss and a 3x notional cap applied. No elapsed-time close was used.

## Programization correction

Audit found that preliminary ML completion features were indexed from the candidate-scan offset rather than the actual run end. They therefore read states roughly 25 seconds after causal completion. The constant event set and action barriers were unaffected, but every preliminary ML output was invalid.

All completion features were realigned to `end_i - 5`; events, labels, OOF calibration, model scores, global-slot routes and account paths were recomputed. Only the corrected figures below are evidence.

## Corrected 2022 economics

The strict global-slot path completed 87 trades for each constant action.

| action | cost | return | NAV multiple | PF | target / stop | mean gross | positive symbol-months |
|---|---:|---:|---:|---:|---:|---:|---:|
| continuation | 12 bp | -24.70% | 0.75296x | 0.276 | 7 / 80 | -1.75 bp | 0 / 5 |
| continuation | 18 bp | -27.57% | 0.72434x | 0.202 | 7 / 80 | -1.75 bp | 0 / 5 |
| continuation | 24 bp | -28.78% | 0.71219x | 0.159 | 7 / 80 | -1.75 bp | 0 / 5 |
| relaxation | 12 bp | -9.61% | 0.90390x | 0.120 | 69 / 18 | +0.79 bp | 0 / 5 |
| relaxation | 18 bp | -12.51% | 0.87488x | 0.0366 | 69 / 18 | +0.79 bp | 0 / 5 |
| relaxation | 24 bp | -14.81% | 0.85192x | 0.0080 | 69 / 18 | +0.79 bp | 0 / 5 |

Relaxation occurred frequently, but the average executable movement was far below cost. Continuation had negative gross value. The corrected HGBT selected only three 2022 events; all three stopped, producing -1.49% at 18 bp. The linear policy selected none.

## Decision

The empirical impact-relaxation phenomenon is not enough to create account alpha under this event and action geometry. Its frequent relaxation targets were too close to entry, while the less frequent adverse extensions dominated risk. The family is retired without changing run length, impact floor, completion ratio, target, stop, cost, model, risk or leverage.

Calendar 2023 and official 2024–2026 were not opened. Ranking and order authority are unchanged. No credentials or orders were used.
