# Hyperliquid finalized liquidation → Bybit structural delivery

## Claim and objective

- Claim: `CLM-20260726-2058-ML-HL-LIQUIDATION-001`.
- Base Project State: revision 13, commit `b7720370c19eaaef337c676f8e556125f5daeed4`.
- Current comparator at registration: Donchian all-breakout `a70626d9e484285f2cb4|all`, preliminary 12-bp UTC-calendar geometric daily growth `0.0900854%`, 24-bp growth `0.0700189%`.
- Objective: find a materially stronger ML information unit rather than tune the comparator. No upper performance cap is imposed.

Hyperliquid misc-event ledger updates explicitly record finalized account liquidations with total liquidated notional, account value, cross/isolated leverage type, and signed coin positions. A positive position size is a liquidated long and therefore forced sell flow; a negative position size is a liquidated short and therefore forced buy flow. This is a direct forced-position event, not a price pattern or inferred crowding proxy.

## Deliberate reduction

The eventual strategy contains exactly:

1. one external information unit: completed Hyperliquid liquidation ledger buckets;
2. one pooled `HistGradientBoostingClassifier`;
3. one frozen isotonic calibration rule;
4. one cost-adjusted `LONG`, `SHORT`, or `FLAT` structural first-passage equation;
5. one global pending/open Bybit slot across `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, and `XRPUSDT`;
6. structural target and invalidation only, with no elapsed-time liquidation.

There is no model family, feature subset, event-window, probability threshold, target, stop, asset, side, session, risk, leverage, or cost grid.

## Non-overlap

The primary state differs from:

- Aave collateral-transfer and debt-repayment liquidations;
- CEX liquidation prints and inferred vulnerable inventory;
- Hyperliquid wallet-skill, TWAP, or parent-order cadence studies;
- exchange open interest, funding, premium, or mark/index acceptance;
- price-only cross-venue lead-lag and the active Binance-to-Bybit passive-maker route;
- direction-neutral movement-hazard OCO;
- Donchian or other completed-bar breakout grids.

## Phase 0: outcome-sealed source gate

The source gate may inspect repository metadata and Hyperliquid misc-event records only. It may not read any Bybit or other market price, future return, first-passage label, model score, action, trade, PnL, official 2026 outcome, credential, or order path.

### Immutable source rule

- Dataset repository: `gionuibk/hyperliquid-misc-events`.
- The probe first resolves the repository's current `main` commit SHA through the Hugging Face API and writes it to evidence **before downloading or parsing any event file**.
- Every selected file is downloaded from that exact immutable SHA.
- File byte counts, repository metadata hashes, content SHA-256 values, row counts, block ranges, parse counts, and liquidation counts are preserved.
- The conditional historical/model stage, if opened, must use the same pinned repository SHA. An updated dataset revision cannot silently replace it.

### Frozen probe sample

The dates are the first and third Mondays of October, November, and December 2025, selected by calendar rule before event counts were observed:

- `2025-10-06`;
- `2025-10-20`;
- `2025-11-03`;
- `2025-11-17`;
- `2025-12-01`;
- `2025-12-15`.

For each date the probe requests the 24 hourly paths:

```text
misc_events_by_block/hourly/YYYYMMDD/H.lz4
H = 0, 1, ..., 23
```

No path containing `2026` is permitted in Phase 0.

### Required liquidation schema

A qualifying record must be an event whose ledger delta has:

```text
type = liquidation
liquidatedNtlPos > 0
accountValue >= 0
leverageType in {Cross, Isolated}
liquidatedPositions = nonempty [{coin, szi}, ...]
```

Each position must have a nonempty coin and a finite, nonzero signed size. The probe preserves block number, block time, local arrival time, event time, event hash, affected users, source path, and the exact liquidation fields. Duplicate identity is defined by `(block_number, event_hash, event_ordinal, ledger_ordinal)`.

### Source gate

The source route opens only if all checks pass:

1. the repository resolves to a nonempty immutable SHA and no selected path contains 2026;
2. at least 132 of 144 frozen hourly files exist and every date has at least 20 files;
3. every downloaded file decompresses and every line is valid JSON with complete block and local-arrival metadata;
4. malformed explicit liquidation deltas: zero;
5. duplicate liquidation identities: zero;
6. at least four of six dates contain one or more explicit liquidation events;
7. total explicit liquidation events: at least 50;
8. at least two of `BTC`, `ETH`, `SOL`, and `XRP` appear in liquidated positions;
9. total target-coin liquidation-position records: at least 25.

A source failure closes this exact transport without creating alpha evidence. A source pass authorizes only the frozen historical/model stage below.

## Conditional historical information and availability

If Phase 0 passes, all Hyperliquid misc events from `2025-10-02 00:00:00 UTC` through `2025-12-31 23:59:59.999 UTC` are read from the same pinned repository SHA. The event availability clock is `local_time`, not nominal block time. Records are sorted by local arrival and block identity; source gaps reset all rolling state and may not be bridged.

Explicit liquidations are aggregated into completed one-second **local-arrival** buckets. A bucket becomes usable only after its final local-arrival second is complete. For each target coin, liquidated long size implies forced sell direction and liquidated short size implies forced buy direction. Coin notional is calculated only from the latest completed, causally available Bybit price before the decision; no event-time or future price is used.

## Bybit structure, entry, and exit

- Execution venue: Bybit USDT-linear perpetuals.
- Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `XRPUSDT`.
- Completed Bybit 60-second bars form external-liquidity pools through two-left/two-right confirmed swing highs and lows.
- A pivot becomes usable only after the second right bar completes.
- A confirmed pool consumed after confirmation is removed.
- At the first executable Bybit quote at least 500 ms after the completed liquidation bucket, freeze the nearest still-unconsumed confirmed high above and low below the entry, searched over the preceding 48 hours.
- An event is ineligible unless both pools exist and each lies at least 24 basis points from the executable entry.
- The label is which frozen pool is reached first.
- Same-timestamp target/stop ambiguity is adverse.
- A source gap after entry receives the full adverse structural loss at the first executable quote, not deletion or favorable marking.
- Exit is only the frozen structural target, frozen opposing structural invalidation, or a strategy-defined opposing forced-flow state that has been fixed before entry. There is no elapsed-time position exit.

## Exactly sixteen model features

Each target-coin event row uses these completed, causal values only:

1. `log1p(total_liquidated_notional_usd)`;
2. `log1p(sum_account_value_usd)`;
3. total liquidated notional divided by `max(sum_account_value, 1)`;
4. liquidation-event count;
5. unique liquidated-account count;
6. account liquidated-notional Herfindahl concentration;
7. cross-margin share of liquidated notional;
8. target-coin signed forced-flow imbalance;
9. target-coin share of total liquidated notional;
10. BTC liquidation-notional share;
11. ETH liquidation-notional share;
12. combined SOL/XRP liquidation-notional share;
13. count of target coins carrying nonzero forced flow in the bucket;
14. local-arrival lag from block time in milliseconds, winsorized only from fit data;
15. prior completed 15-minute target return divided by prior completed 60-minute realized volatility;
16. upper and lower structural distances represented as one signed log distance ratio, `log(upper_distance/lower_distance)`.

Training-only medians impute missing numeric values. No unknown liquidation amount is invented. No wallet identity skill, later account outcome, future mark, MFE, MAE, backward-smoothed state, future liquidation, or label-derived value is a feature.

## One model and calibration rule

```text
HistGradientBoostingClassifier(
    learning_rate=0.05,
    max_iter=160,
    max_leaf_nodes=9,
    min_samples_leaf=30,
    l2_regularization=1.0,
    random_state=20260726
)
```

- Fit: `2025-10-02 00:00:00 UTC` through `2025-10-31 23:59:59.999 UTC`.
- Calibration: November 2025.
- Untouched confirmation: December 2025.
- Official 2026H1 remains mechanically prohibited until every confirmation gate passes.

If November contains at least 100 resolved labels and both classes, fit one isotonic map on November predictions. Otherwise the route fails the calibration/sample gate; raw probabilities are not substituted.

The exact non-fitted baseline is structural distance:

```text
p_up_baseline = lower_distance / (upper_distance + lower_distance)
```

## One action and account rule

For calibrated probability `p_up`, executable entry-relative pool distances, and full modeled round-trip cost:

```text
EV_LONG  = p_up * upper_distance - (1 - p_up) * lower_distance - cost
EV_SHORT = (1 - p_up) * lower_distance - p_up * upper_distance - cost
```

Choose the larger positive value only when it exceeds an additional fixed 5-bp decision margin; otherwise remain flat. The same event and action paths are replayed at 12, 18, and 24 basis points, with actual funding added when crossed.

- Initial NAV: 10,000 USDT.
- Base planned structural-loss risk: 0.5% NAV.
- Fixed initial notional cap: 3x NAV.
- Quantity is the minimum of structural-loss risk, margin/liquidation-distance, 0.25% of the prior completed minute's quote turnover, and 5% of executable top-quote quantity.
- One global pending/open slot across all four symbols.
- Event arbitration: maximum 24-bp expected net utility, then model probability margin over baseline, then stable symbol order.
- The largest 10% of positive 24-bp event keys and the top five positive event keys are excluded before complete slot, sizing, funding, and NAV replay.
- No risk or leverage search is allowed before a positive, robust base edge exists.

## Confirmation gate before official 2026H1

Every item must pass:

1. at least 150 resolved December labels and both classes;
2. model ROC AUC exceeds the distance baseline by at least 0.02;
3. positive Brier skill against the distance baseline;
4. at least 60 completed one-global-slot trades at 24 bp;
5. positive 24-bp mean and median account return, profit factor at least 1.20, and positive total return;
6. both chronological December halves positive at 24 bp;
7. at least two of the three ten-day December segments positive at 24 bp;
8. top-five positive-PnL share no greater than 35%;
9. 24-bp total return remains positive after both frozen winner-removal tests;
10. base 24-bp UTC-calendar geometric daily growth at least `0.10%` and winner-removed growth at least `0.05%`;
11. no forced liquidation, terminal NAV destruction, or unresolved account path.

This is an advancement floor, not a performance ceiling. A result above 1% daily growth is retained at full strength.

## Conditional official 2026H1

Only after all confirmation gates pass:

1. refit the unchanged HGBT on October-November 2025 resolved rows;
2. fit the unchanged isotonic map on December 2025 resolved rows;
3. freeze code, features, structure, arbitration, sizing, costs, and all gates at `2025-12-31 23:59:59 UTC`;
4. open `2026-01-01` through `2026-06-30` once as one continuous Bybit account path.

A ranking-eligible result requires exact Bybit executable BBO/depth, actual funding, latency, capacity, liquidation-distance, winner-removal, and all UTC calendar days. A positive base edge may then open a separately preregistered wide risk/leverage/capacity search. A negative result is retired without adjacent feature, bucket, threshold, symbol, target, stop, risk, or leverage rescue.

## Authority

Research only. No credentials, paper orders, testnet orders, live orders, or bank integration are permitted.
