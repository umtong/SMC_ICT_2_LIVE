# Conditional pre-2024 GMX V1 removed-exposure ML contract

Claim: `CLM-20260726-2324-ML-GMX-V1-LIQUIDATION-001`

Recorded before the outcome-sealed source gate produced any event count, market row, label, model metric, trade or PnL.

## Economic mechanism

A canonical GMX V1 `LiquidatePosition` event proves that a BTC- or ETH-indexed leveraged position was deleted from the Vault after liquidation state 1. It does **not** prove an external market order. The model receives the signed removed exposure as inventory-state information and may learn continuation, exhaustion reversal or flat.

1. Finalized `LONG_REMOVED` and `SHORT_REMOVED` events become usable after 120 seconds.
2. Completed events are aggregated into five-minute source buckets.
3. At the decision time, only market bars already completed before the source bucket are used.
4. The nearest completed prior-60-minute upper and lower liquidity pools are frozen.
5. One pooled HGBT estimates upper-pool-first probability for BTCUSDT and ETHUSDT.
6. One cost-adjusted equation selects long, short or flat; the chosen pool is target and the opposite pool is stop.
7. One global BTC/ETH slot is enforced. No elapsed-time liquidation exists.

## Fixed source features

- total removed size;
- signed removed exposure share;
- long-removed fraction;
- BTC-indexed fraction;
- event count and unique accounts;
- event-size HHI and maximum share;
- realized-PnL-to-size and collateral-to-size ratios;
- completed prior 15-minute return, 60-minute volatility, path efficiency, taker-flow imbalance and volume;
- frozen upper/lower structural distances;
- completed BTC/ETH breadth.

GMX Vault mark price is accounting/oracle context only and is not used as a Bybit fill or external impact price.

## Chronology

- train: 2021-09-01 through 2022-06-30;
- calibration: 2022H2;
- untouched confirmation: 2023H1;
- conditional development: 2023H2;
- official 2024H1 opens immediately only after the unchanged pre-2024 system survives.

A label must resolve inside its own partition. Same-minute dual contact is excluded from fitting and treated stop-first in account replay. An unresolved position is marked at the partition boundary and is never described as a strategy close.

## Model and account

Exactly one `HistGradientBoostingClassifier`: learning rate 0.05, 120 iterations, seven leaves, minimum leaf 20, L2 1.0, seed 20260727. Training medians and at most one isotonic calibration map are allowed. The non-fitted baseline is causal structural distance.

The same decisions are replayed at 12, 18 and 24 basis points with Binance funding proxy in the pre-2024 fatal screen, 0.5% structural-loss risk, 3x cap and one global slot. Risk/notional search opens only after positive non-concentrated development and may not change the information unit.

## Advancement

Confirmation requires prediction lift over structural distance, positive Brier skill, breadth across both chronological halves, at least 30 cost-sized trades, positive PF, nonnegative 24-bp return, positive exact winner-removal reroute and no liquidation.

Development requires positive 24-bp return, positive 18-bp return in both quarters, positive median, at least 40 trades, positive exact winner-removal reroute, MDD below 30%, no liquidation and 24-bp daily growth above the current official first-place benchmark `0.0387317%` per UTC calendar day.

Failure retires this exact information unit without feature, threshold, side, target, stop, risk or leverage rescue. Passage freezes the highest-growth no-liquidation risk/notional path that remains positive after winner removal and immediately opens official 2024H1 under unchanged rules.

No credentials or orders.
