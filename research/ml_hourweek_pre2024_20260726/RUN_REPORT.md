# Run report — RES-20260726-ML-HOURWEEK-PRE2024-2024H1-001

## Decision

The exact hour-of-week Ridge family is retired. A filter selected strictly from 2023H2 was frozen at 2023-12-31 and then lost at 18 and 24 basis points in the first official 2024H1 interval.

## Minimal trader-readable system

1. One pooled causal Ridge model estimates the next 24-hour return from completed trend, volatility, quote volume, taker flow and cross-asset state.
2. A 2023H2-only tournament selects one session, direction set, asset subset and threshold multiplier.
3. Entry occurs at the next hourly open.
4. A position exits when its signed expected edge is no longer positive or a superior eligible opportunity takes the one global slot.
5. There is no elapsed-time liquidation.

The selected frozen route was **all UTC hours, long-only, BTCUSDT/SOLUSDT/XRPUSDT, threshold multiplier 0.75**.

## Pre-2024 selection

At 24bp the 2023H2 path returned **+160.79%**, grew **0.522298% per UTC calendar day**, made 42 trades, had PF 3.5678, MDD 21.92% and a positive median. Removing the largest winner event keys before slot competition and rerouting the account still returned **+140.70%**.

This was sufficient to open 2024H1 immediately. No additional pre-gate was added.

## Official 2024H1

| Cost | Total return | Geometric daily growth | Trades | PF | MDD | Median trade |
|---:|---:|---:|---:|---:|---:|---:|
| 12bp | +2.12% | +0.011545% | 80 | 1.1017 | 35.94% | -0.5267% |
| 18bp | -2.66% | -0.014829% | 80 | 1.0674 | 36.47% | -0.5864% |
| 24bp | -7.22% | -0.041195% | 80 | 1.0344 | 37.00% | -0.6460% |

At 24bp, Q1 returned +28.39% but Q2 lost 27.74%. Exact event-key winner removal produced **-12.02%**, **-0.070319% per day**, PF below one and a negative median.

The 12bp path was still approximately 87 times below the 1% daily objective and became negative after exact winner removal. The family is therefore structurally distant, not merely fee-sensitive.

## Ranking consequence

`RES-20260726-ML-HOURWEEK-XRP-001` is retained only as a selected-development diagnostic. Its 720 filters were chosen after observing the complete 2024-2025 path, so it was not a system available at the 2023-12-31 cutoff and cannot lead the active causal strategy ranking.

## Next alpha

No additional UTC session, asset, side, threshold, feature, risk or leverage tuning is authorized. Research switches to externally observed inventory and forced-flow information: stablecoin issuance/destruction, Uniswap WETH-stable inventory transfer and finalized liquidation flow.

## Authority

2024H2 through 2026H1 remain unopened under this family. No paper, testnet or live order was submitted.
