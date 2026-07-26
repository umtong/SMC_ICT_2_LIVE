# Hyperliquid wallet-flow to Bybit execution research

## Work Claim

`CLM-20260726-1040-HL-WALLET-FLOW-001`

## Objective-first distinction

This work does not tune any ranked bar, tape, OI, liquidation, L2, premium or ordinary cross-venue threshold. It tests whether **identified Hyperliquid account inventory transitions** contain causal information that reaches executable Bybit USDT-linear perpetual prices with enough residual magnitude and repetition to matter after realistic costs.

The information unit is a wallet cohort selected only from information available before the signal. The intended mechanisms are:

1. skilled-cohort opening consensus and TWAP inventory continuation;
2. skilled-cohort closing consensus and liquidation-distorted exhaustion;
3. disagreement between historically skilled and persistently adverse cohorts;
4. incomplete Bybit incorporation after the Hyperliquid block/fill becomes locally observable.

Trading, if later opened, is restricted to Bybit `BTCUSDT`, `ETHUSDT`, `SOLUSDT` and `XRPUSDT`, with one global entry/position slot. Hyperliquid is signal data only.

## Stage 0 — frozen source inventory

`preregistration_v1.json` permits only anonymous public-source metadata and file inventory. It prohibits reading returns, labels, wallet performance, trade outcomes or strategy PnL. The purpose is to identify exact sample dates, schemas, file sizes and hashes before freezing a date-specific causal experiment.

The first source probe targets the public Kaggle dataset `marvingozo/hyperliquid-l1-order-flow-microstructure-10-perps`, whose advertised streams are wallet-level orders/fills, L2 snapshots and funding/open-interest data. A source is not trusted from its description; the workflow records endpoint responses and requires file-level inventory before any scientific use.

## Promotion boundary

After the inventory is observed, a second preregistration must freeze all of the following before any outcome data is read:

- immutable source version and hashes;
- exact fit/development/untouched partitions permitted by coverage;
- wallet eligibility, skill estimation and cohort update rules;
- event-time aggregation, feed latency and Bybit execution latency;
- candidate grid, price-only exit logic, costs, funding, risk sizing and one-slot replay;
- event-count, median, cost, concentration and cross-partition gates;
- the boundary that keeps 2024-01-01 through 2026-06-30 sealed.

If the public sample cannot support ex-ante wallet selection plus at least two distinct development partitions, the sample is data-insufficient for strategy PnL. The dependency may then be tested only after obtaining a longer point-in-time source; it must not be rescued by inspecting sample outcomes first.

No credentials, orders, testnet, paper trading or live trading are used.