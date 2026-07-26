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

## Decision-ready result

`RES-20260726-ML-LIQUIDITY-DRAW-001` is hard-valid at the initial causal fatal-screen stage and economically `BELOW_GATE`.

- 15,854 fit-confirmation event rows; 15,831 resolved; 375 authorized actions.
- Model AUC: `0.693656`; distance-only structural baseline AUC: `0.734865`; AUC lift: `-0.041210`.
- Model Brier score: `0.224404`; distance baseline Brier: `0.208793`; Brier skill: `-0.074766`.
- 12 bp: 156 trades, `-5.2115%`, geometric daily growth `-0.05816%`, median `-52.45 bp`, winner-removed return `-12.3856%`.
- 18 bp: 156 trades, `-9.1929%`, geometric daily growth `-0.10476%`, median `-58.43 bp`, winner-removed return `-16.4685%`.
- 24 bp: 156 trades, `-12.4182%`, geometric daily growth `-0.14402%`, median `-64.42 bp`, winner-removed return `-19.6946%`.
- Only November was positive at every cost; October and December were negative.
- Every economic and model-lift gate except raw model AUC, sample size and trade count failed.
- Untouched 2023 remained physically unopened; 2024–2026 remained sealed; no orders were submitted.

The result shows that the selected candle-state feature set did not add information beyond the two structural distances. Do not tune adjacent HGBT parameters, probability advantage, pivot width, feature list or cost threshold under this dependency. Reopen only after changing the information unit materially. The next proposed unit is event-conditioned L2 acceptance-versus-rejection after a causal external-liquidity raid.

## Evidence

- workflow run: `30194348946`
- artifact: `8629624480`
- artifact digest: `sha256:e986870c95f524a5c6a872d38534b5714111746f215096c722ff9ee62986a817`
- scientific source SHA-256: `87957a81a70cc9c777f555bb23ccbeb2ecae50c50ff0d730ce72de974b30c741`
- artifact result SHA-256: `991b8663ca4623cdbe0821f149943175ef3fab9056a984517afb399bda7bf794`

## Promotion boundary

This exact model is retired. The cumulative strategy ranking and live-order permission remain unchanged.
