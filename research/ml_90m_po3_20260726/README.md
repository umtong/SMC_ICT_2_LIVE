# Minimal supervised 90-minute PO3 router

Claim: `CLM-20260726-1807-ML-90M-PO3-001`

This study keeps **one SMC/ICT mechanism, one pooled model, eight readable features and one trade route**.

## Explanation to an SMC/ICT trader

Every 90-minute cycle is anchored to America/New_York midnight and divided into three completed 30-minute thirds:

1. **Accumulation** — the first 30 minutes freeze the dealing-range high and low.
2. **Manipulation** — the second 30 minutes must raid exactly one boundary and close back inside. A low raid defines a possible long; a high raid defines a possible short.
3. **Distribution** — at the third-third open, the model estimates whether price will deliver to the untouched accumulation boundary before invalidating beyond the actual manipulation extreme.

The stop is structural, beyond the raid. The target is structural, at the opposite accumulation boundary. There is no elapsed-time liquidation.

## ML core

The sole model is a standardized regularized logistic regression trained on 2021. It receives exactly eight sign-normalized features: sweep depth, reclaim strength, manipulation return, manipulation efficiency, rejection wick, relative volume, accumulation compression and prior six-hour return. It predicts **target before stop**, not future return directly.

Only probability thresholds `0.55`, `0.65` and `0.75` exist. A candidate must also have positive expected value after the 24bp stress before it can compete for the one global account slot.

## Staging

- 2021: model training only.
- 2022: frozen calibration and at most one selected threshold.
- 2023: opened only after the complete 2022 gate.
- 2024H1 through 2026H1: opened only after the complete 2023 gate, with causal half-year refits on resolved prior events.

The initial OHLC execution screen uses official Bybit native five-minute archives, identical 12/18/24bp replay, 2% planned NAV loss, a 10x notional cap and a prior-volume participation limit. A survivor is still not deployable until unchanged exact Bybit BBO/depth and actual-funding replay.
