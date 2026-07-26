# Minimal cross-venue L2 sweep router

This study keeps one question: after Bybit BTCUSDT raids a completed five-minute boundary, does Binance Futures displayed liquidity support accepted continuation or reveal a failed sweep?

## Trader-readable rule

1. Freeze the previous completed five-minute Bybit high and low as external liquidity.
2. Wait for the next block to raid exactly one side.
3. Wait one full second; no entry exists during the unfinished raid second.
4. Read one calibrated ML probability built from Binance top-five depth additions, withdrawals, imbalance, microprice and aggressive flow, plus Bybit's measured sweep/reclaim state.
5. Compare the probability-weighted structural value of:
   - continuation toward a half-range extension, or
   - rejection reversal toward the untouched opposite boundary.
6. Enter only when one route clears the full 24-bp contract plus a fixed 5-bp margin. Otherwise do nothing.
7. The two structural objectives are target and stop. No elapsed-time liquidation is used.

The model is not allowed to invent a third pattern, choose a different target, search a threshold, or increase risk to rescue weak predictions.

## Stage boundary

2022 January/March/May train the one HGBT, July calibrates it, and September/November are frozen confirmation. The exact unchanged rule may download January/March/May 2023 only after every fit gate passes. All 2024-2026 URLs are rejected in code.
