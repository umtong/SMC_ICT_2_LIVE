# Preregistration — ML XRPL DEX inventory lead

## Claim

`CLM-20260726-2250-ML-XRPL-DEX-001`

This route tests a source that is economically different from completed CEX price patterns: finalized XRP Ledger DEX inventory transfer and price discovery in long-established USD gateway order books. The hypothesis is that ledger-native XRP/USD displacement and volume shocks sometimes reveal XRP inventory demand before the Bybit linear perpetual fully reprices.

The route is not selected because any earlier strategy worked. Earlier records are used only to avoid overlapping active work.

## Phase 1: outcome-sealed source gate

Phase 1 is allowed to open only:

- the deterministic token identities `GateHub USD` and `Bitstamp USD`;
- XRPL.to 15-minute OHLCV responses for five frozen seven-day windows ending before 2024;
- official full-history XRPL Clio `ledger_index` and `book_changes` responses needed to verify that at least one selected historical candle corresponds to actual finalized XRP/token movement.

Phase 1 must not open Bybit candles, future returns, labels, models, strategy PnL, any 2024–2026 market outcome, credentials, or orders.

### Frozen source windows

- 2021-05-03 through 2021-05-09 UTC
- 2022-01-10 through 2022-01-16 UTC
- 2022-11-07 through 2022-11-13 UTC
- 2023-06-05 through 2023-06-11 UTC
- 2023-11-06 through 2023-11-12 UTC

The interval is 15 minutes. The API parameter syntax is probed through three preregistered variants because the current public documentation and deployed endpoint may differ. The parser accepts only finite, positive OHLC and nonnegative volume with timestamps inside the frozen window.

### Pass rule

At least one issuer must satisfy all of:

1. at least three nonempty frozen windows;
2. at least three windows with positive reported volume;
3. at least 120 valid in-window candles;
4. at least 30 positive-volume candles.

In addition, an official full-history Clio server must directly confirm at least one positive-volume candle by finding finalized `book_changes` for `XRP_drops` against the exact issuer and currency during one of the two possible 15-minute timestamp interpretations.

Passing opens the frozen pre-2024 model stage. Failing closes this source route before any market outcome is inspected.

## Phase 2 contract, opened only after a pass

The model stage will use only information available by each decision time.

- Tradable venue and product: Bybit `XRPUSDT` USDT linear perpetual.
- Event clock: completed 15-minute XRPL DEX candle; entry cannot occur before the next Bybit executable price after completion.
- Features: gateway-specific DEX returns, volume shocks, cross-gateway consensus/disagreement, DEX–Bybit premium, and contemporaneous completed Bybit state. No future extrema, future fills, or confirmed-later pivots.
- Model family: one histogram gradient boosting model with a fixed causal retraining recipe. No model zoo.
- Position slot: one global pending/open position.
- Exit: structural first passage to a pre-entry target, stop, or opposite inventory-state invalidation. No elapsed-time forced exit.
- Costs: 24 bp primary round-trip all-in screen, with 12/18/36 bp sensitivity only after positive primary performance.
- Pre-2024 sequence: train and calibrate in chronological blocks ending no later than 2023-12-31. System structure, selection rule, sizing update rule, execution rule, and retraining method must be frozen before 2024H1 is opened.
- Official progression: only a materially positive, trade-broad, winner-removal-positive pre-2024 result may open 2024H1. A weak result is not rescued with leverage.

No 2024H1 result produced by a revised system may be described as a new independent test of the same observations.

## Reproducibility

Every HTTP body is stored with URL, status, response headers when available, byte count, and SHA-256. Official RPC responses are represented by ordered response hashes and exact matching-ledger payloads. The workflow uploads the source evidence as an immutable GitHub Actions artifact.
