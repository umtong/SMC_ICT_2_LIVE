# Reproducible Ridge UTC-state XRP V2

Claim: `CLM-20260726-ML-HOURWEEK-XRP-V2-001` / issue #252.

This is a source-complete successor, not a parity claim for `RES-20260726-ML-HOURWEEK-XRP-001`. The earlier 58-trade implementation and ledger were not retained, and bounded independent reconstruction did not satisfy its exact parity targets.

## Frozen system

A pooled `StandardScaler + Ridge(alpha=10)` uses completed Binance USD-M BTC/ETH/SOL/XRP hourly trend, volatility, quote-volume, taker-flow, breadth, dispersion and UTC time-state features. The target is the log return from the next hourly open to the open 24 hours later. Before every half-year, the model is refit using only labels resolved before the cutoff. The threshold is the prior 183-day 95th percentile of absolute predictions.

Only XRPUSDT is eligible. Completed decision bars opening at UTC 06:00–13:00 can authorize LONG or SHORT when absolute predicted return exceeds `1.25 × max(prior threshold, 0.75 × cost)`. Entry is the next hourly open. A position exits only when signed expected edge becomes nonpositive; an eligible opposite edge reverses the position. There is no maximum holding duration.

## Reproduced selected development

Immutable Actions artifact `8616632878`; artifact ZIP SHA-256 `fd3c20704cf4b8b1dc80023298920456d4ec7cf2dfe9986237d94ea8cbd51f4c`.

At 24bp plus an adverse one-bp-per-eight-hours pro-rata funding reserve over 2024–2025:

- 30 trades;
- NAV `3.967036266140347x`;
- geometric daily growth `0.18868932457136722%`;
- PF `6.392903332003452`;
- median trade `+3.584219847144529%`;
- MDD `9.458750000000005%`;
- all four half-years positive.

Blocking the largest three positive-PnL entry keys before rerouting leaves NAV `2.8910081826397582x` and `0.14533194699264396%/day`, with every half-year positive.

Session start 06 and multiplier 1.25 were selected using the complete 2024–2025 development path. This reference is not OOS.

## One-shot official evaluation

The workflow first reproduces the immutable development ledger, then downloads official Binance hourly signal data and Bybit XRP hourly execution data. It replays 24/72/96bp paths with actual Bybit funding when sufficiently complete and an adverse fallback otherwise. The 2026H1 model uses only information available by 2025-12-31. No rule may change after 2026 data are opened.

Research only. No credentials or orders.
