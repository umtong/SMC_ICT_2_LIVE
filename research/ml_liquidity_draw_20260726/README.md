# ML external-liquidity draw / first-passage research

Claim: `CLM-20260726-1703-ML-LIQUIDITY-DRAW-001`

## One mechanism, not another pattern library

An SMC/ICT trader describes price as being drawn toward external liquidity. This study turns that statement into one testable ML problem:

> Given the nearest **already confirmed and still-unreached** buy-side and sell-side external-liquidity pools, which one will Bybit reach first?

The two pools are frozen before entry. A nonlinear classifier estimates the probability that the upper pool is reached first. The strategy is allowed to trade only when that probability, the two structural distances and an 18 bp signal-cost contract imply a probability advantage of at least five percentage points over the exact break-even probability. There is no library of entries, no post-hoc chart naming and no adjacent threshold grid.

For a long, the upper pool is the target and the lower pool is the stop. For a short, the lower pool is the target and the upper pool is the stop. Target, stop, source-gap treatment and one-global-slot arbitration are fixed before the outcome is read.

## Why it is distinct

- It predicts a **first-passage ordering between two causal structural barriers**, not the next candle return.
- It does not require a sweep, FVG, order block, breaker, OTE, Silver Bullet or CRT setup to authorize an entry.
- It does not place two-sided OCO orders or predict direction-neutral movement hazard.
- It does not use L2 post-decision state, cross-venue latency or cross-asset follower lag.
- BTC and ETH are the only initial markets. SOL and XRP are deliberately deferred unless the core information unit survives.

## Frozen causal contract

- Bybit USDT-linear `BTCUSDT` and `ETHUSDT` public one-minute archives.
- Fifteen-minute bars are complete only after all 15 constituent minutes exist.
- A pivot is usable only after two completed bars to its right; its level and origin time are then frozen.
- A pool is retired after a completed 15-minute bar trades through it.
- Decisions occur once per completed hour and enter only at the next one-minute open.
- Labels and exits scan forward from that entry. A minute that touches both pools is ambiguous for model fitting and is a stop-first loss in account replay.
- A source gap ends the label scan; an accepted unresolved position is charged its full structural stop at the available boundary.
- No elapsed-time liquidation exists.
- One global pending/open position across BTC and ETH.
- NAV-risk quantity, 3x notional cap, prior completed 15-minute participation cap, and identical 12/18/24 bp cost paths.

## ML and sequential opening

One `HistGradientBoostingClassifier` is trained on causally resolved January–June 2022 rows. Its scores are calibrated once on causally resolved July–September 2022 rows. The frozen model is tested on October–December 2022.

The model must beat the exact distance-only first-passage baseline, not merely a 50/50 classifier. The untouched 2023 source is downloaded only when **every** preregistered fit gate passes. Source access to 2024, 2025 and 2026 is rejected by code.

## Promotion boundary

Even a fit and 2023 survivor remains an initial candle-data screen. Promotion requires a separately frozen sequential 2024–2026 replay with historical Bybit executable quotes/depth, actual funding and the full project account contract. No credential, paper order, testnet order or live order is used here.
