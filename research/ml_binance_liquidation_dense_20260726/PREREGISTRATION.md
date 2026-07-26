# Dense COIN-M forced-liquidation flow → Bybit structural-delivery ML

## Claim and economic mechanism

Claim: `CLM-20260726-2020-ML-BINANCE-LIQ-DENSE-001`.

This route tests an explicit forced-flow information unit, not another completed-candle pattern:

1. a completed Binance COIN-M account liquidation transfers vulnerable inventory at an exchange-recorded time;
2. BTC and ETH liquidation breadth, side consensus, concentration and impact efficiency distinguish continuing forced delivery from an exhausted sweep;
3. already-confirmed, unconsumed Bybit BTCUSDT/ETHUSDT external-liquidity pools define targets and stops;
4. one pooled HGBT estimates upper-pool-first probability;
5. one cost-adjusted `LONG / SHORT / FLAT` equation controls the single global Bybit slot;
6. exits occur only at structural target, structural stop or completed strategy invalidation—never because time elapsed.

## Pre-outcome source correction

Before any source row or market outcome opened, the original USD-M archive assumption was corrected by
`CORRECTION-20260726-ML-BINANCE-LIQ-COINM-SOURCE-001`.

The authoritative source is now:

```text
data/futures/cm/daily/liquidationSnapshot/BTCUSD_PERP/
data/futures/cm/daily/liquidationSnapshot/ETHUSD_PERP/
```

Signal mapping is fixed:

```text
BTCUSD_PERP liquidation → Bybit BTCUSDT
ETHUSD_PERP liquidation → Bybit ETHUSDT
```

COIN-M is signal-only. Every account result is measured on Bybit USDT-linear perpetuals.

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
- BUY and SELL liquidation records are both observed;
- at least 500 decoded sample rows;
- at least 75% of sample archives are nonempty;
- duplicate identity fraction is below 10%;
- the market/model/PnL/official-period seal remains intact.

Source identities are symbol plus `(timestamp, side, effective price, effective quantity)`.
COIN-M contract counts are preserved raw in this gate. Dollar normalization must use a separately verified historical contract specification before model fitting.

No price chart, future return, first-passage label, model metric, action, trade, PnL or 2024–2026 outcome may open during this gate.

## Conditional pre-2024 ML system

Only a source PASS opens this fixed model stage.

### Availability

A liquidation row becomes usable after its provider timestamp, completion of the containing one-minute bucket and a fixed five-second operational delay. Completed market, funding, premium and OI states must also be available by that time. Gaps reset rolling state and no label or position may cross them.

### Structural map

Completed 15-minute Bybit-proxy bars form pivot highs and lows with two completed bars on each side. A pivot becomes usable only after both right-side bars close. The nearest unconsumed high and low are frozen at decision time.

### One model and fourteen trader-readable features

One pooled `HistGradientBoostingClassifier` with one frozen isotonic map estimates upper-pool-first probability from:

1. signed forced contract count;
2. absolute forced contract count;
3. event count;
4. unique-price concentration;
5. same-side share;
6. BTC/ETH liquidation breadth;
7. forced flow relative to prior quote volume;
8. price-impact efficiency;
9. completed 1m, 5m and 15m returns;
10. prior realized volatility;
11. prior available OI change;
12. prior available funding/premium;
13. upper structural distance;
14. lower structural distance.

No future return, MFE, MAE, post-decision liquidation, hindsight pivot or later OI is a feature.

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

A failure retires this exact information unit without adjacent feature, threshold, target, stop, risk or leverage rescue.

A survivor is reconstructed on exact Bybit BBO, mark, funding, latency, partial-fill/capacity, margin and continuous NAV. Only then is the broad prewritten risk/notional frontier searched using information through 2023-12-31. The highest sustainable no-liquidation growth path is frozen without a 1% ceiling and official 2024H1 opens immediately.

Weak 2024H1 performance retires the route and changes alpha. Promising performance follows the predetermined causal half-year update method through 2026H1. No credentials or orders are permitted.
