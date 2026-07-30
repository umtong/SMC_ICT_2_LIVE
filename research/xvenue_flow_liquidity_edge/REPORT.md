# Cross-venue taker-flow value at prior-day liquidity interactions

## Decision

`RES-20260730-XVENUE-FLOW-LIQUIDITY-EDGE-CORE-001` is **`RETIRED_2022H1_FLOW_SENSOR_NOT_CORE`**.

The unchanged prior-day liquidity interaction family is broad, but adding completed Binance USD-M taker flow, price-impact efficiency, activity state and BTC/ETH peer flow did not create a cost-surviving Bybit Core. Calendar 2022H2 and every later period remain sealed.

## Why this test was run

The inherited repeated-level study showed a large and broad future-information action oracle but only a sparse unstable causal model. The registered Bybit 500 ms source intended to supply the missing contemporaneous information covered only three first days and eight usable level events, so that exact dependency was closed before model or PnL. This test changed only the information sensor: official full-minute Binance USD-M flow was joined to the already-frozen Bybit events and exact action outcomes.

## Frozen mechanics

- Bybit prior-day high/low, scale, rearm, `BREAK` and `REJECT` geometry: unchanged from `RES-20260730-MINIMAL-REPEATED-LEVEL-CORE-001`.
- New data only: Binance one-minute quote volume, taker-buy quote volume, trade count and price.
- Features end at the last Binance minute completed by the Bybit decision time.
- Training: November–December 2021, 416 resolved action rows.
- First forward screen: 2022H1, 1,210 resolved action rows.
- Fixed HGBT, direct 24-bp Bybit account return, positive best action versus flat.
- Inherited account: 500 ms execution, actual Bybit funding, 0.5% risk, 3x cap, one slot, 12/18/24 bp, no elapsed-time exit.

## Programization audit

A completed zero-volume Binance minute is a valid market state. The first implementation treated zero quote volume and zero trade count as missing in the 30-day activity normalization, causing those optional z-scores to remain unavailable for 30 days after a 64-minute maintenance/no-trade interval on 2022-05-01. The implementation was corrected before final interpretation:

- `log1p(0)` is retained for quote volume and trade count;
- average trade size remains missing when trade count is zero;
- all core 1m/5m/15m flow and return windows were complete at every event;
- the complete result was regenerated twice from scratch.

The correction did not rescue the economics.

## Model information

| Diagnostic | Price/OI baseline | Flow-augmented |
|---|---:|---:|
| MAE skill vs action constant | 0.1571% | -1.0810% |
| MSE skill vs action constant | -2.4379% | -5.5223% |
| Prediction/realized Spearman | 0.0135 | -0.0391 |
| Positive action predictions | 135 | 185 |
| Mean realized return when predicted positive | -0.0968% | -0.1251% |

The external flow model was worse than the action-specific constant and worse than the inherited price/OI baseline. Its positive predictions realized negative mean value and its rank correlation was negative.

## One-slot 2022H1 economics

| Policy | Cost | Trades | NAV multiple | PF | Median completed return | MDD |
|---|---:|---:|---:|---:|---:|---:|
| Price/OI HGBT | 24 bp | 107 | 0.891440x | 0.570 | 0.0085% | 11.15% |
| Flow HGBT | 12 bp | 144 | 0.886898x | 0.675 | -0.4674% | 11.47% |
| Flow HGBT | 18 bp | 144 | 0.865430x | 0.609 | -0.4955% | 13.57% |
| Flow HGBT | 24 bp | 144 | 0.846930x | 0.551 | -0.4956% | 15.37% |
| Flow HGBT, winner deleted/rerouted | 24 bp | 138 | 0.798795x | 0.399 | -0.4975% | 20.18% |

The flow model increased trade breadth from 107 to 144 but admitted lower-value actions. At 24 bp it lost 15.31%; deleting seven largest positive event keys and rebuilding the account increased the loss to 20.12%. Event-bootstrap q05 NAV was 0.779037x.

## Interpretation

Directional taker flow was weakly associated with less-bad action outcomes in some univariate slices, but it did not provide enough independent information to overcome the negative event base. Binance and Bybit price/flow states are highly contemporaneously correlated; the external flow mostly described the same move rather than revealing local Bybit absorption, replenishment or queue resistance.

This is an economic failure of the exact external sensor, not a remaining event-timing or account bug. Do not rescue it with a flow threshold, horizon, model, action geometry, cost, risk, leverage or additional SMC gate. A future successor requires materially new local order-consumption/replenishment evidence or another independent economic source.

No credentials or orders were used.
