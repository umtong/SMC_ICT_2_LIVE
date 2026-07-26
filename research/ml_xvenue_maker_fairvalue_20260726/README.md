# Cross-venue fair-value maker ML

`CLM-20260726-2036-ML-XVENUE-MAKER-001`

## The one economic idea

A completed Binance Futures BTCUSDT top-book/aggressor-flow shock moves the external executable fair value while Bybit BTCUSDT is still stale. Rather than pay taker cost to chase the move, the system joins the stale Bybit best quote post-only. It keeps that order only while the external fair-value premise remains valid and the same L1 queue remains observable.

In SMC/ICT language, Binance supplies the completed displacement and Bybit supplies an unrepriced liquidity edge. Entry is not authorized by the name of a setup. One fixed two-stage ML model must estimate both passive fill probability and, conditional on fill, structural delivery to frozen fair value before reference reversal.

## Why this is different

- PR #46 V5D is exact-arrival **taker** execution; this claim tests passive entry economics and queue-aware fill.
- Same-venue maker studies predict local spread capture/toxicity; this claim requires an external fair-value displacement.
- SMC mitigation-maker studies rest at a retracement level; this claim rests only at the current stale executable best quote.
- The position has no timeout. Pending cancellation and filled exit are entirely structural.

## Causal execution

A 100ms signal state must finish before the 100ms or 300ms latency begins. The order price and queue come from the last known BBO immediately before activation. Later aggressive volume is counted only when every same-side trade in that 100ms bin is at or through the order price. Cancellation ahead is never credited. Losing top-quote identity cancels the order because deeper-book queue position is unknown.

## Initial screen

- train: 2022-07-01
- isotonic calibration: 2023-03-01
- untouched confirmation: 2023-07-01
- BTCUSDT only in stage one
- one global pending/open slot
- 12/18/24bp round-trip stress
- 0.5% planned NAV risk, 3x cap, 5% displayed-quote participation
- 2024-2026, credentials and all order paths prohibited

Both latency paths must survive. A survivor is still not rank eligible until the unchanged unit is expanded pre-2024 and replayed with actual Bybit funding.
