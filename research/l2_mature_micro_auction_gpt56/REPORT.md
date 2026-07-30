# L2-adjudicated mature micro-auction delivery

## Decision

`RES-20260730-L2-MATURE-MICRO-AUCTION-001` is `RETIRED_SPARSE_AND_NEGATIVE_L2_MATURE_AUCTION`.

This fatal screen retained the SMC/ICT sequence but replaced the chart's guess about liquidity resistance with actual Bybit top-five cancellation/replenishment state. A short-horizon range first had to mature as a two-sided one-minute auction. Its first completed boundary raid was then classified only when the exact post-raid L2 state agreed with the bar's structural acceptance or rejection.

- `ACCEPT`: close outside the frozen boundary and raid-direction continuation score above the opposite-direction refill/reversal score;
- `ABSORB`: close back inside and the opposite-direction refill/reversal score above continuation;
- acceptance target: one full frozen-range extension;
- absorption target: untouched opposite boundary;
- structural stop/state loss only, no elapsed-time close.

The L2 source used provider local timestamps. The account deliberately entered at the first canonical one-minute open strictly after the exact L2 executable-entry timestamp, so no fill was backdated.

## Funnel

Across the three sparse sample days, BTC and ETH produced only eight executable actions. March context contained six. May development contained one BTC absorption trade. July unchanged confirmation contained one ETH acceptance trade.

The low count was not caused by missing L2 rows: every mature raid found a later L2 state. Most candidate ranges breached before maturity, the fixed L2 score comparison correctly returned flat, or the conservative later-minute execution left invalid stop/target geometry.

## Economics

| Stage | trades | 0bp | 12bp | 24bp | PF at 24bp |
|---|---:|---:|---:|---:|---:|
| March context | 6 | 1.01727x | 0.99533x | 0.98717x | 0.091 |
| May development | 1 | 1.00004x | 0.99644x | 0.99565x | 0.000 |
| July confirmation | 1 | 0.99941x | 0.99581x | 0.99536x | 0.000 |

The only confirmation trade stopped and lost even before cost. Winner-event deletion and full one-slot rerouting worsened the March diagnostic.

## Interpretation

Actual L2 state did not rescue a chart-derived mature-range event. The exact event was too sparse to be a Core, and the two forward trades did not support a stable sign. Reducing maturity requirements or changing the range scale after observing scarcity would be adjacent rescue.

The next executable-liquidity study must begin from the order book itself: a persistent price-level wall that exists before price arrives, its actual consumption, and whether that same level replenishes or disappears. Chart structure may provide context, but it cannot be the condition that destroys event breadth before the liquidity information is tested.

## Boundary

Do not change range scale, maturity counts, score comparison, target, stop, cost, symbol/side, risk, leverage or ML. Sparse first-day data cannot certify full-calendar growth. Official 2024–2026 remained sealed; no credentials or orders were used.
