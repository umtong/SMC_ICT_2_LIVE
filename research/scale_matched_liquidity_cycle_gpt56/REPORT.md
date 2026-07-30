# Scale-matched liquidity-cycle fatal screen

## Decision

`RES-20260730-SCALE-MATCHED-LIQUIDITY-CYCLE-001` is `RETIRED_PRE2024_NAIVE_PIVOT_PAIR_TRANSLATION_FAILURE`.

The hypothesis came directly from the transcript-grounded SMC/ICT logic: after one side of a meaningful external-liquidity range has been consumed and order flow shifts away from that source, internal liquidity in the delivery direction should be lower resistance and the paired opposite external pool of the same scale should be the destination.

## Frozen first translation

- causal radius-2 one-hour pivots;
- first observed one-minute trade through one live side;
- completed 15-minute reclaim and opposite-swing break;
- protected source-to-shift extreme;
- paired opposite one-hour pivot as target;
- immediate shift entry or first later genuine 5-minute FVG rebalance;
- actual funding, fixed 500 ms, one global slot, 0.5% NAV risk, 3x cap and 12/18/24 bp;
- no elapsed-time exit.

## Economics

Both actions failed before official data opened. At 24 bp, `SHIFT_NOW` ended 0.4807x in 2022 over 1,023 trades and 0.2768x in unchanged 2023 over 1,085 trades. The genuine-FVG action ended 0.4138x in 2022 over 881 trades and 0.3187x in 2023 over 866 trades. Winner-event deletion and complete slot rerouting worsened the paths.

The failure was not merely cost. The FVG action was below initial NAV at zero cost in both 2022 and 2023; `SHIFT_NOW` was nearly flat at zero cost in 2022 and negative in 2023.

## Programization diagnosis

Timing, pool consumption, target availability, actual funding and barrier ordering were internally consistent. The material error was semantic: every small radius-2 one-hour pivot pair was labelled a same-scale dealing range. This produced roughly six to seven new “external pools” per day per symbol without proving that a two-sided balance had accumulated inventory there.

That is not what the source logic says. Scale matching is an inventory statement, not a timeframe label. A genuine balance must first show a mature two-sided auction; only then can a boundary raid be interpreted as manipulation and the opposite boundary as distribution.

## Boundary

Retire the exact paired-pivot implementation. Do not tune pivot width, FVG size, target, stop, side, symbol, cost, risk or leverage after observing the result. A separate balance-manipulation-distribution family may be preregistered because it changes the economic state definition rather than tightening the failed event filter.

Official 2024-2026, ML, risk search and orders remained unopened.
