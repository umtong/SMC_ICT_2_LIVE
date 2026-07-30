# Dynamic cross-asset flow-decay audit

**Result:** `RES-20260729-DYNAMIC-FLOW-NOTIME-AUDIT-001`  
**Decision:** **official 2024H1 economic failure; exact family retired.**

## Why this candidate was worth correcting

Candidate `021fbab613517a31ad98` was the strongest recorded broad-trade dynamic-factor path: 194 completed 2023 trades and positive 12/18/24 bp results. Its implementation nevertheless contained two current-contract defects:

1. surviving positions closed after 96 five-minute bars even when neither the structural stop nor the flow-decay state exit occurred;
2. a completed signal entered at the exact next five-minute open, although that price existed before the required 500 ms activation. Flow-state exits had the same one-bar timing defect.

The audit changed only those execution semantics. The rank transition, beta window, residual horizon, cross-sectional rank threshold, flow threshold, structural stop, risk, capacity and cost paths remained fixed.

## Exact source reproduction

The verified source reproduced the registered 2023 path exactly:

| cost | trades | return | geometric daily | PF | MDD |
|---:|---:|---:|---:|---:|---:|
| 12 bp | 194 | +23.1615% | +0.057092% | 1.502 | 4.63% |
| 18 bp | 194 | +16.6299% | +0.042156% | 1.360 | 5.41% |
| 24 bp | 194 | +11.1846% | +0.029051% | 1.243 | 6.21% |

Exit reasons were 96 protective stops, 59 flow-decay exits and 39 prohibited 96-bar exits.

## Defect decomposition

Removing only the elapsed-time exit did **not** destroy the nominal 2023 alpha. At 24 bp it increased the path to +14.8789%, because many positions eventually reached a stronger flow-decay exit.

Correcting activation while keeping the timeout reduced 24 bp return to +6.8547%. Removing the timeout as well left a still-positive but fragile result:

- 191 trades;
- +6.8009% total return;
- +0.018028% geometric daily growth;
- PF 1.140;
- MDD 10.48%;
- median account return -19.77 bp;
- top-five positive-PnL share 40.72%;
- exact top-10%-all-trade removal -31.29%;
- 106 protective stops and 85 flow-decay exits;
- maximum completed holding path 458 five-minute bars.

The main program distortion was therefore the premature next-open entry/state exit, not the mere existence of the timeout. The corrected route nevertheless remained cost-positive with meaningful breadth, so opening the frozen 2024H1 gate was justified.

## Official 2024H1

No parameter, symbol, cost, risk or state change was made after 2023.

| cost | trades | return | geometric daily | PF | MDD |
|---:|---:|---:|---:|---:|---:|
| 12 bp | 78 | **-7.5793%** | -0.043298% | 0.657 | 10.16% |
| 18 bp | 78 | **-8.8990%** | -0.051197% | 0.601 | 11.30% |
| 24 bp | 78 | **-10.0604%** | -0.058242% | 0.551 | 12.30% |

At 24 bp, 46 of 78 positions hit the structural stop and only 32 reached a flow-decay exit. Median account return was -50 bp, top-five positive-PnL share was 72.55%, and exact top-10% winner removal produced -19.25%.

This is not a remaining software-timing ambiguity or a sparse one-trade failure. The same cross-sectional residual/rank/flow state changed sign at broad opportunity count in the first official interval.

## Decision

The exact candidate and its dependency family are retired. Reintroducing a maximum holding duration, selecting a different residual or flow threshold, narrowing the symbols after seeing 2024, or increasing risk/leverage would be a rescue of failed official evidence rather than a new information source.

A full-2024 path was inadvertently computed in the same local batch after the H1 calculation. It was not used for any selection or interpretation and is excluded from authoritative evidence because the claim authorized H2 only after positive H1.

No Bybit-native expansion, later official interval, credential, paper order or live order was opened.
