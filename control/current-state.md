# Current state

- revision: 16
- phase: ACTIVE_RESEARCH
- current first place: `FIRST-20260726-ML-HOURWEEK-XRP-0815-125`
- first-place stage: `PROVISIONAL_CAUSAL_SEQUENTIAL_REFIT_SELECTED_DEVELOPMENT_BINANCE_PROXY`
- target_status: `NOT_MET`
- live_order_permission: none
- repository: `umtong/SMC_ICT_2_LIVE`

## Current first place

The provisional first place is the causal Ridge UTC-state route `UTC08-15 / BOTH / XRPUSDT / threshold 1.25` from `RES-20260726-ML-HOURWEEK-XRP-001`.

- model: one pooled Ridge using completed trend, volatility, quote-volume, taker-flow, cross-sectional state and asset-specific UTC hour-of-week/hour-of-day interactions
- sequential refits: before 2024H1, 2024H2, 2025H1 and 2025H2 using only prior information
- entry: next hourly open, XRPUSDT only, UTC 08:00-15:59, absolute expected return at least 1.25 times the prior-only calibrated threshold
- exit: signed expected edge no longer positive or a stronger eligible alternative exists; no elapsed-time liquidation
- 12/24-bps geometric daily growth: `0.232573% / 0.223030%`
- 24-bps NAV multiple and total return: `5.0964x / +409.639%`
- 1% target gap at 24 bps: `0.776970 percentage points per UTC calendar day`
- trades: `58`; PF: `4.8808`; MDD: `25.81%`; median trade: `+2.1499%`
- directions: `51` long, `7` short; mean holding time `36.31` hours
- top-five positive-PnL share: `33.65%`
- 2024H1/H2 and 2025H1/H2 returns: `+1.03% / +159.93% / +75.77% / +10.42%`
- exact top-10%-of-all-trades winner removal before slot rerouting: `3.6051x`, `0.175579%/day`, all four halves positive
- 72-bp stress: `0.184867%/day`; 96-bp stress remains profitable overall but 2025H2 is slightly negative

It replaces the former Donchian first place because its 24-bp growth is `3.185x` higher, its median trade is positive, concentration is lower, and the fully rerouted winner-removal paths remain strongly positive. It is not a final solution: the 720 filter tournament was selected on the complete 2024-2025 development path, market data are a Binance proxy, funding is a conservative proxy, exact Bybit BBO/depth and margin/liquidation distance are absent, and official 2026H1 remains sealed.

## Cumulative strategy ranking

1. ML UTC08-15 XRP state machine — `0.223030%`/day at 24 bps; 58 trades; positive exact winner-removal path.
2. Donchian all-breakout `a70626d9e484285f2cb4|all` — `0.0900854%`/day at 12 bps and `0.0700189%` at 24 bps; winner-removal failure.
3. Donchian after-loser `a70626d9e484285f2cb4|after_loser` — `0.0829996%`/day at 12 bps; winner-removal failure.
4. CME gap competing-risk ML — `0.0459425%`/day at 12 bps; negative median and winner concentration.
5. Bybit liquidity-mass rejection — `0.0118550%`/day at 12 bps; 23 trades and complete top-five concentration.
6. 08:00 option-settlement SMT — `0.0099556%`/day at 18 bps; 12 trades.
7. Bybit MMXM lifecycle — `0.00575058%`/day at 12 bps; negative median and losing second half.
8. KRW-relative regional SMT reversal — `0.00487483%`/day at 12 bps; two trades.
9. Liquidation exhaustion reversal — `0.00358316%`/day at 18 bps; sparse and winner-removal failure.

All remain below the 1% reference and none has deployment authority. Rank creates no incumbency protection.

## Selection and validation boundary

The base model and hold/switch policy were selected on 2023. Each half-year model is causal, but the session/asset/side/threshold filter was selected after observing the full 2024-2025 path. Therefore this is selected development, not sealed OOS. The forward boundary is frozen at `2025-12-31 23:59:59 UTC`; official 2026H1 has not been opened.

Fixed leverage is not used to inflate the rank. On the same path, 4x reaches only about `0.713%/day` with `97.5%` MDD and liquidation begins near `4.05x`. The unlevered one-times path is the ranking metric.

## Current objective

Do not protect or polish the new first place. It is still about `4.48x` short of the 1% daily-growth reference. The highest-information next step is an unchanged exact-Bybit replay of the selected route across 2024-2025, followed by the first frozen 2026H1 evaluation only after data, execution, funding and account contracts are fixed.

External forced-flow and inventory-transfer ML source routes remain active because a new route must still close the remaining objective gap rather than merely validate this provisional benchmark.

## Next exact action

1. Reconstruct exact Bybit hourly BBO/depth, funding, capacity and liquidation-distance inputs for the frozen `UTC08-15 / XRP / 1.25` route without changing the model or filter.
2. Verify the same 2024-2025 path under exact Bybit execution and continuous marked NAV.
3. Freeze code and open official 2026H1 once; insert the result immediately whether it exceeds or loses the current first place.
4. Continue materially distinct forced-flow and inventory-transfer ML paths in parallel; do not return to Donchian or generic completed-bar parameter grids.

Updated: 2026-07-26 22:12 KST
