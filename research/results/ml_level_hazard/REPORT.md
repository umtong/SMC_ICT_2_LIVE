# Repeated prior-day liquidity-level survival ML — pre-2024 decision

## Decision

`RES-20260729-ML-LEVEL-HAZARD-001` is **TESTED_BELOW_GATE**. The exact repeated-level survival information unit is retired. Calendar 2023 and the official continuous 2024-01-01 through 2026-06-30 account interval were not opened.

The screen found modest ability to classify which structural boundary would be reached first, but no account path combined meaningful opportunity breadth, 18/24 bp cost survival and exact winner-removal survival.

## Economic mechanism tested

A completed prior UTC-day high or low became a frozen, causally available liquidity level on the next UTC day. Each separated revisit updated the level's state: touch count, time since prior contact, prior rejection distance, prior penetration, approach compression, directional efficiency and the contemporaneous Bybit leveraged-position state.

At each completed 15-minute interaction, one pooled BTC/ETH logistic model selected:

1. breakout through the level;
2. rejection away from the level;
3. abstention.

This was a survival-hazard model of a known level before the break, not a post-breakout continuation rule or another post-sweep candle pattern.

## Frozen evaluation

- Source: verified canonical Bybit pandas export, manifest SHA-256 `8de81d791c9ad177c6fd2046675adda759dc7373aa1d31e01b32d9b7058e8c6d`.
- Products: Bybit `BTCUSDT` and `ETHUSDT` USDT-linear perpetuals.
- Fit: calendar 2021 events whose structural outcomes resolved before 2022-01-01.
- Forward selection: calendar 2022 events whose outcomes resolved before 2023-01-01.
- Level life: 3 / 5 / 7 UTC days.
- Touch tolerance: 0.10 / 0.20 completed-state scales.
- New-touch separation: 2 / 4 / 8 completed 15-minute bars.
- Symmetric structural boundaries: 0.50 / 0.75 / 1.00 scales.
- Models: standardized pooled logistic regression, `C` 0.1 / 1 / 10.
- Expected-R thresholds: 0 / 0.05 / 0.10 / 0.20 / 0.30 / 0.50 / 0.75 / 1.00.
- Fixed order activation delay: 500 ms; entry at the first later observed one-minute open.
- Same-minute dual-boundary contact: adverse stop first.
- One global pending/open BTC/ETH slot.
- Planned loss: 0.5% of current NAV; notional cap: 3x NAV.
- Cost replays: 12 / 18 / 24 bp all-in round trip plus exact signed Bybit funding.
- Exit: the first frozen structural boundary; no elapsed-time liquidation.

The complete screen covered **54 topologies** and **1,296 model/threshold account paths**. There were 159 positive paths at 12 bp, 42 at 18 bp, and only one at 24 bp. No 24 bp-positive path retained at least 100 trades. Maximum validation AUC was 0.6251 and minimum Brier score was 0.2421.

## Best path with meaningful opportunity breadth

The best path retaining at least 100 trades used:

- five-day level life;
- 0.20-scale touch tolerance;
- two-bar touch separation;
- 1.00-scale boundaries;
- logistic `C=1`;
- expected-R threshold 0.75.

Its 2022 results were:

| Cost | End NAV | Return | UTC geometric daily growth | Trades | PF | Closed-trade MDD |
|---|---:|---:|---:|---:|---:|---:|
| 12 bp | 12,576.94 | +25.77% | +0.06284% | 125 | 1.4862 | 8.82% |
| 18 bp | 10,713.76 | +7.14% | +0.01889% | 125 | 1.1457 | 11.22% |
| 24 bp | 9,583.81 | -4.16% | -0.01165% | 125 | 0.9088 | 14.79% |

At 18 bp, only 36 of 125 trades were positive, the median notional return was **-24.90 bp**, and the top five positive trades contributed 27.05% of positive PnL. The path therefore depended on a relatively thin positive tail despite reasonable trade count.

Exact removal of the top `ceil(10% × 125) = 13` positive selected event IDs, followed by a full rerun of the global router, reduced the 18 bp path to **8,013.27 USDT** with 113 replacement-aware trades. The same removed IDs produced 8,587.92 USDT at 12 bp and 7,651.90 USDT at 24 bp.

## Sole 24 bp-positive path

The only path with positive 24 bp ending NAV used a seven-day level life, 0.20-scale tolerance, eight-bar separation, 1.00-scale boundaries, logistic `C=0.1`, and threshold 1.00.

- 24 bp NAV: **10,147.07 USDT**.
- UTC geometric daily growth: **0.00400%**.
- Completed trades: **50**.
- PF: **1.0825**.
- Closed-trade MDD: **6.43%**.
- Positive / negative trades: **15 / 35**.
- Median notional return: **-26.78 bp**.
- Top-five positive-PnL share: **52.61%**.

Removing its top five positive selected event IDs and rerunning the router reduced the 24 bp account to **9,186.97 USDT**. The same deletion reduced the 18 bp account to 9,401.45 USDT. It was therefore a sparse tail path, not a repeatable core engine.

## Interpretation

Repeated contact history carried some directional information: broader topologies reached validation AUC values near 0.61, and a small number of paths were positive at moderate costs. But that information did not produce robust account alpha.

The failure pattern is economically clear:

- median trades remained negative;
- the 125-trade path changed sign between 18 and 24 bp;
- the only 24 bp-positive path had only 50 trades;
- both representative paths became negative after exact winner removal;
- even the positive headline growth rates remained far below the required 1% per UTC calendar day.

The correct response is not higher risk, larger leverage, a narrower probability threshold, longer boundary distance or 2023 tuning. Those would rescue the observed outcomes rather than the frozen hypothesis. This exact level-survival formulation is closed.

## Validation and project effect

Focused tests cover:

- next-UTC-day level availability and clustered-level causal de-duplication;
- one global slot and deterministic highest-edge selection;
- exact winner deletion followed by full same-time alternative rerouting;
- immutable primary action and threshold under 12/24 bp replay.

The underlying shared execution tests also cover fixed 500 ms activation, first later one-minute entry, adverse same-minute boundary ambiguity and signed funding by position side.

- Result Registry / cumulative ranking: unchanged; this is pre-2024 below-gate evidence.
- Live-order permission: unchanged; none.
- Calendar 2023 opened: no.
- Official 2024-2026 opened: no.
- Reusable components: causal repeated-level state construction, replacement-aware winner-removal rerouting and the global-slot simulator remain useful, but the tested strategy is not endorsed.
