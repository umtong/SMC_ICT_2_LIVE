# Source and hypothesis synthesis

## Pre-cutoff YouTube concepts

The videos below are hypothesis sources rather than performance evidence.

1. **Faares Q — “The Beginner's Guide to Making Money with Crypto Arbitrage”** (`bXNGACsNXbY`, 2023-01-29). The useful primitive is that the same underlying can trade at different prices in segmented markets, but only discrepancies larger than all execution costs are economically meaningful. The project does not copy the video's transfer or cross-exchange workflow.
2. **Real Vision — “What Is Basis and Arbitrage Yield Trading?”** (`cGddRFr1rsE`, 2022-03-21). The useful primitive is that separate participant preferences can create basis, while simultaneous execution and convergence risk matter. The project translates this into a one-way price-discovery test rather than claiming risk-free arbitrage.

A deep search did not identify a credible pre-2024 video that specifically demonstrated Bybit USDC-perpetual-to-USDT-perpetual predictive alpha. That absence is preserved: the exact rule is an original, falsifiable translation of broader segmentation and basis concepts, not a claim that a video strategy was profitable.

## Current official mechanism material

Current Bybit help material describes USDC perpetuals as USDC-quoted and USDC-settled contracts and documents a session-settlement mechanism tied to the funding interval. Those pages were updated after the historical information cutoff. They are used only to confirm that USDC and USDT contracts are distinct product pools; funding and settlement-clock effects are explicitly excluded from this historical rule.

## Public data

Bybit's public archive exposes daily raw trades for `BTCPERP`, `ETHPERP`, `BTCUSDT` and `ETHUSDT`. Required fields are:

- `timestamp`;
- `symbol`;
- aggressor `side`;
- `size`;
- `price`;
- `trdMatchID`.

The feasibility probe opened three disclosed 2023 dates before validation preregistration. It found approximately 0.02-0.15 USDC-perpetual trades per second, versus approximately 2-6 trades per second in the corresponding USDT instruments on the first probe date. The signal is therefore tested only at completed USDC matching events with an additional 100 ms latency; no continuous or queue-level lead is inferred.

## Quantitative translation

| Concept | Frozen observable |
|---|---|
| segmented-market move | log return between consecutive exact-timestamp USDC trade groups |
| already incorporated move | USDT log return over the identical pair of USDC event timestamps |
| USDC innovation | USDC return minus same-interval USDT return |
| participant control | signed USDC aggressor notional divided by total USDC event notional |
| executable response | first USDT trade at or after event completion plus 100 ms |
| economic relevance | identical gross paths replayed at 12, 18 and 24 bp |

## Explicit exclusions

No historical rule uses current product settings, session-settlement timestamps, funding, mark/index/premium candles, spot-perpetual basis, USDCUSDT stablecoin timing, cross-venue quotes, dated futures, COIN-M collateral, liquidation labels, displayed order-book depth or post-2023 video material.
