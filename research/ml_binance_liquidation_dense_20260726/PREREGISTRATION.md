# Published COIN-M forced-liquidation snapshots → Bybit structural-delivery ML

## Claim and economic mechanism

Claim: `CLM-20260726-2020-ML-BINANCE-LIQ-DENSE-001`.

This route tests an explicit forced-flow publication state, not another completed-candle pattern:

1. Binance publishes a COIN-M forced-liquidation order snapshot with positive executed quantity;
2. BTC and ETH published-snapshot breadth, side consensus, concentration and impact efficiency distinguish continuing forced delivery from an exhausted sweep;
3. already-confirmed, unconsumed Bybit BTCUSDT/ETHUSDT external-liquidity pools define targets and stops;
4. one pooled HGBT estimates upper-pool-first probability;
5. one cost-adjusted `LONG / SHORT / FLAT` equation controls the single global Bybit slot;
6. exits occur only at structural target, structural stop or completed strategy invalidation—never because time elapsed.

## Pre-outcome source corrections

Before any decision-ready source PASS, market row, label, model metric, trade or PnL opened, the original USD-M archive assumption was corrected by `CORRECTION-20260726-ML-BINANCE-LIQ-COINM-SOURCE-001`.

The authoritative source is now:

```text
data/futures/cm/daily/liquidationSnapshot/BTCUSD_PERP/
data/futures/cm/daily/liquidationSnapshot/ETHUSD_PERP/
```

Signal mapping is fixed:

```text
BTCUSD_PERP published liquidation snapshot → Bybit BTCUSDT
ETHUSD_PERP published liquidation snapshot → Bybit ETHUSDT
```

COIN-M is signal-only. Every account result is measured on Bybit USDT-linear perpetuals.

### Contract-count normalization

`CORRECTION-20260726-ML-BINANCE-LIQ-COINM-CONTRACT-NOTIONAL-003` binds the inverse-contract units:

- raw quantity is a contract count;
- USD notional is `published executed contract count × hash-recorded exchangeInfo.contractSize`;
- base-asset quantity is a diagnostic `USD notional / effective price`;
- `effective price × contract count` is prohibited.

### Snapshot censoring and executed-fill rule

`CORRECTION-20260726-ML-BINANCE-LIQ-SNAPSHOT-CENSORING-EXECUTED-FILL-004` binds the official publication semantics:

- for each symbol Binance publishes at most the latest one liquidation order in each 1,000ms interval;
- the archive is therefore a censored lower-bound observation, not a complete liquidation ledger;
- no published row does not prove that no liquidation occurred;
- total exchange liquidation volume, complete order count and cross-venue market share may not be inferred;
- all count, breadth, side-share, concentration and size features refer only to published snapshots;
- executed contract count is accumulated filled quantity when positive, otherwise last-filled quantity when positive, otherwise zero;
- original unfilled quantity may never become executed forced flow;
- zero-executed rows are retained only in source diagnostics and excluded from signal/model rows.

Only a source artifact generated from a branch head containing corrections 003 and 004 may open the model stage. Earlier queued or completed artifacts are non-authoritative.

## Phase 0 — outcome-sealed source gate

The fixed source range is `2021-01-01` through `2023-12-31`.

The gate uses the public Binance Vision S3 ListObjectsV2 endpoint, verifies the daily key set, downloads only the twenty preregistered symbol/date samples, verifies every corresponding `.CHECKSUM`, and decodes exactly one CSV from each archive.

Frozen sample dates:

- 2021-01-29, 2021-05-19, 2021-09-07, 2021-12-04;
- 2022-05-12, 2022-06-13, 2022-11-09;
- 2023-03-10, 2023-08-17, 2023-10-23.

The source gate passes only if all are true:

- both BTCUSD_PERP and ETHUSD_PERP prefixes are present;
- each symbol covers at least 80% of the 1,095 fixed UTC dates;
- every frozen sample date exists for both symbols;
- BUY and SELL published executed snapshots are both observed;
- at least 500 positive-executed sample snapshots;
- at least 75% of sample archives contain a positive-executed snapshot;
- exact published-snapshot duplicate identity fraction is below 10%;
- snapshot censoring, executed-fill and contract-count semantics are bound in the result;
- the market/model/PnL/official-period seal remains intact.

Source identities are symbol plus `(timestamp, side, effective price, published executed contract count)`. COIN-M contract counts are preserved raw in this gate. Dollar normalization requires separately verified and hash-recorded contract specifications before model fitting.

No price chart, future return, first-passage label, model metric, action, trade, PnL or 2024–2026 outcome may open during this gate.

## Conditional pre-2024 ML system

Only a current-head source PASS opens this fixed model stage.

### Availability

A published snapshot becomes usable only after its provider timestamp, completion of the containing one-minute bucket and a fixed five-second operational delay. Completed market, funding, premium and OI states must also be available by that time. Gaps reset rolling state and no label or position may cross them.

### Structural map

Completed 15-minute Bybit-proxy bars form pivot highs and lows with two completed bars on each side. A pivot becomes usable only after both right-side bars close. The nearest unconsumed high and low are frozen at decision time.

### One model and fourteen trader-readable features

One pooled `HistGradientBoostingClassifier` with one frozen isotonic map estimates upper-pool-first probability from:

1. signed published executed-contract snapshot magnitude;
2. absolute published executed-contract snapshot magnitude;
3. published executed-snapshot count;
4. published unique-price concentration;
5. published same-side share;
6. BTC/ETH published-snapshot breadth;
7. published executed snapshot notional relative to prior quote volume;
8. price-impact efficiency conditional on published snapshots;
9. completed 1m, 5m and 15m returns;
10. prior realized volatility;
11. prior available OI change;
12. prior available funding/premium;
13. upper structural distance;
14. lower structural distance.

These variables characterize the exchange-published forced-flow state. They are never represented as complete liquidation totals. No future return, MFE, MAE, post-decision snapshot, hindsight pivot or later OI is a feature.

### Chronology

- fit: 2021-01-01 through 2022-06-30;
- calibration: 2022-07-01 through 2022-12-31;
- untouched confirmation: 2023-01-01 through 2023-06-30;
- conditional development: 2023-07-01 through 2023-12-31;
- official 2024H1 opens immediately after the complete system is frozen through 2023-12-31.

No label crosses a partition boundary.

### Action and account

At the first executable minute open after the information delay:

```text
EV_LONG  = p_up * upper_distance - (1-p_up) * lower_distance - all_in_cost
EV_SHORT = (1-p_up) * lower_distance - p_up * upper_distance - all_in_cost
```

Take only the larger strictly positive action; otherwise remain flat. BTCUSDT and ETHUSDT share one global slot. The same chronological decisions are replayed at 12, 18 and 24bp. Same-minute target/stop ambiguity is stop-first. Source-boundary unresolved positions receive the structural adverse loss plus exit cost. There is no elapsed-time liquidation.

The initial measurement path uses 0.5% planned structural-loss risk and a 3x notional cap only to measure base edge.

## Advancement and immediate official evaluation

Untouched confirmation and development must independently show model skill, positive 24bp return and median trade, positive chronological halves, positive exact winner-removal rerouting, controlled concentration and no forced liquidation.

A failure retires this exact published-snapshot information unit without adjacent feature, threshold, target, stop, risk or leverage rescue.

A survivor is reconstructed on exact Bybit BBO, mark, funding, latency, partial-fill/capacity, margin and continuous NAV. Only then is the broad prewritten risk/notional frontier searched using information through 2023-12-31. The highest sustainable no-liquidation growth path is frozen without a 1% ceiling and official 2024H1 opens immediately.

Weak 2024H1 performance retires the route and changes alpha. Promising performance follows the predetermined causal half-year update method through 2026H1. No credentials or orders are permitted.
