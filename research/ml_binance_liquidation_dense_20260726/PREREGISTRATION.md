# Dense forced-liquidation flow → structural liquidity delivery ML

## Claim and economic reason

Claim: `CLM-20260726-2020-ML-BINANCE-LIQ-DENSE-001`.

The repeated failure mode of prior sparse liquidation studies was not merely a weak threshold. Public first-day samples produced too few independent forced-flow episodes to determine whether forced deleveraging contains information beyond price distance. This route first establishes whether Binance publishes a continuous, checksum-verifiable USD-M `liquidationSnapshot` history. It does not rescue any previous liquidation strategy.

The trader-readable mechanism is:

1. completed forced liquidations reveal a real transfer of vulnerable inventory rather than an inferred candle pattern;
2. multi-asset liquidation breadth, flow concentration, price impact efficiency and contemporaneous leverage state distinguish a continuing cascade from an exhausted sweep;
3. already-confirmed, still-unconsumed external liquidity pools define the only permitted targets and stops;
4. one ML probability is converted to cost-adjusted `LONG`, `SHORT` or `FLAT`;
5. the one global Bybit position exits only at structural target, structural stop or completed strategy invalidation—never by elapsed time.

## Phase 0: outcome-sealed official source gate

The authoritative transport is Binance Vision's official public S3 bucket and the corresponding `data.binance.vision` download host. The gate enumerates both possible public layouts:

```text
data/futures/um/monthly/liquidationSnapshot/<SYMBOL>/
data/futures/um/daily/liquidationSnapshot/<SYMBOL>/
```

The fixed range is January 2021 through December 2023 for `BTCUSDT`, `ETHUSDT`, `SOLUSDT` and `XRPUSDT`.

Every consumed ZIP must have a matching `.CHECKSUM`, contain exactly one CSV, decode under the frozen liquidation-order schema, remain within its stated UTC period and contain no invalid timestamp, side, quantity or price. Identities are `(timestamp, side, effective_price, effective_quantity)` within each archive. No price chart, future return, label, model metric, action, trade or PnL may be opened in this phase.

Monthly layout is preferred if it covers at least 90% of the fixed months and contains all fixed January/April/July/October samples. Daily layout is the fixed fallback if it covers at least 80% of fixed days and contains all ten preregistered stress dates. The source gate also requires:

- all four symbols observed;
- both BUY and SELL liquidation records;
- at least 500 decoded fixed-sample rows;
- at least 75% of fixed sample archives nonempty;
- duplicate fraction below 10%;
- intact outcome seal.

Failure closes this exact official `liquidationSnapshot` transport before outcomes. It is not interpreted as negative alpha.

## Conditional pre-2024 ML system

Only a source PASS authorizes the unchanged history/model stage.

### Information availability

A liquidation record becomes usable only after its provider timestamp and completion of the containing one-minute bucket, plus a fixed five-second operational delay. Features use only completed records and completed market/OI/funding states. Source gaps reset every rolling state and prohibit labels or positions from crossing the gap.

### Structural map

For each permitted market, completed 15-minute bars create pivot highs and lows with two bars on each side. A pivot becomes known only when both right-side bars close. A pivot consumed before confirmation is never used; a confirmed pivot is removed after consumption. The nearest unconsumed high and low are frozen at decision time.

### One fixed model

Exactly one pooled `HistGradientBoostingClassifier` with a fixed seed estimates upper-pool-first probability. A single isotonic map is used only if the prewritten calibration sample-count and two-class condition are met; otherwise raw probabilities remain.

Fixed causal features are limited to:

1. signed liquidation notional in the completed event bucket;
2. absolute liquidation notional;
3. event count;
4. unique-price concentration;
5. same-side liquidation share;
6. BTC/ETH/SOL/XRP liquidation breadth;
7. liquidation notional relative to prior completed sixty-minute quote volume;
8. price-impact efficiency;
9. completed one-, five- and fifteen-minute returns;
10. prior completed realized volatility;
11. prior available OI change;
12. prior available funding/premium state;
13. upper structural distance;
14. lower structural distance.

No future label, MFE, MAE, later liquidation record, wallet identity, post-decision OI or hindsight pivot is a feature.

### Frozen chronology

- fit: `2021-01-01` through `2022-06-30`;
- calibration: `2022-07-01` through `2022-12-31`;
- untouched confirmation: `2023-01-01` through `2023-06-30`;
- conditional development: `2023-07-01` through `2023-12-31`;
- official 2024H1: opened immediately only after the unchanged complete system is frozen through `2023-12-31`.

No label may cross a partition boundary.

### Economic action and account path

At the first executable minute open after the fixed information delay, the model probability and structural distances produce one expected-value comparison:

```text
EV_LONG  = p_up * upper_distance - (1-p_up) * lower_distance - all_in_cost
EV_SHORT = (1-p_up) * lower_distance - p_up * upper_distance - all_in_cost
```

The larger positive action is selected; otherwise the system remains flat. The same chronological decisions are replayed at 12, 18 and 24 basis points. Same-minute dual target/stop contact is adverse-first. Source-boundary unresolved positions receive the structural adverse loss plus cost. One pending/open position blocks every other symbol.

The initial measurement path uses 0.5% planned structural-loss risk and a 3x notional cap only to measure the base edge. These are not final safety ceilings.

### Advancement gate

Untouched confirmation and conditional development must each independently satisfy the prewritten requirements:

- model AUC exceeds the structural-distance baseline;
- positive Brier skill against that baseline;
- at least 50 completed global-slot trades at 18bp;
- positive total return and median trade at 24bp;
- positive 18bp return in both chronological halves;
- positive 18bp return after removing the top five winners and the top 10% positive event keys before complete rerouting;
- top-five positive-PnL share no greater than 35%;
- MDD below 30%;
- zero liquidation or irrecoverable account path.

A failure retires this exact information unit without feature, threshold, target, stop, risk or leverage rescue.

## Immediate official sequential evaluation

A pre-2024 survivor is reconstructed on exact Bybit BBO, mark, funding, latency, partial-fill/capacity and NAV. The broad risk frontier—0.25% to 60% planned loss and 1x to 100x notional cap—is searched only with information through 2023-12-31 under the unchanged model and decision rule. Paths with forced liquidation or irrecoverable account damage are excluded; the highest sustainable after-cost geometric-growth path is frozen. The objective is not capped at 1%.

That frozen system opens official `2024-01-01` through `2024-06-30` immediately. If performance is structurally far from the objective, the information unit is retired and research changes alpha. If promising, data through 2024-06-30 update the prewritten system for 2024H2, continuing causally through 2026H1.

No credentials or orders are permitted in this research.
