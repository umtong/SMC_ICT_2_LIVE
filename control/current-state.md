# Current state

- revision: 17
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
- 12/24-bp geometric daily growth: `0.232573% / 0.223030%`
- 24-bp NAV multiple and total return: `5.0964x / +409.639%`
- 1% target gap at 24 bp: `0.776970 percentage points per UTC calendar day`
- trades: `58`; PF: `4.8808`; MDD: `25.81%`; median trade: `+2.1499%`
- directions: `51` long, `7` short; mean holding time `36.31` hours
- top-five positive-PnL share: `33.65%`
- 2024H1/H2 and 2025H1/H2 returns: `+1.03% / +159.93% / +75.77% / +10.42%`
- exact top-10%-of-all-trades winner removal before slot rerouting: `3.6051x`, `0.175579%/day`, all four halves positive
- 72-bp stress: `0.184867%/day`; 96-bp stress remains profitable overall but 2025H2 is slightly negative

It replaced the former Donchian first place because its 24-bp growth is `3.185x` higher, its median trade is positive, concentration is lower, and the fully rerouted winner-removal path remains strongly positive.

It is still a provisional benchmark, not a final solution. The 720 filter tournament was selected using the complete 2024-2025 development path, Binance data and adverse funding are proxies, exact Bybit BBO/depth, capacity and liquidation distance are absent, and official 2026H1 remains unopened.

Rank does not determine research priority.

## Official 2024H1 Donchian ML result

`RES-20260726-ML-DONCHIAN-2024H1-SEQUENTIAL-001` froze one pooled HGBT accept-or-flat filter using information available through `2023-12-31` and opened `2024H1` as a sequential research interval.

### Unfiltered route at 24 bp

- total return: `+1.8461%`
- geometric daily growth: `0.0100516%`
- completed trades: `49`
- PF: `1.10905`
- MDD: `12.6997%`
- median completed trade: `-50 bp`
- top-five positive-PnL share: `91.42%`

### Frozen HGBT filter at 24 bp

- total return: `+7.3021%`
- geometric daily growth: `0.0387317%`
- target gap: `0.9612683 percentage points per UTC calendar day`
- completed trades: `24`
- PF: `1.87120`
- MDD: `10.1656%`
- median completed trade: `-50 bp`
- top-five positive-PnL share: `100%`
- winner-removal reroute: `-7.6610%`
- model MAE skill versus the constant baseline: `-1.6897%`

The filter improved the unchanged 2024H1 route but remained structurally far below the objective, had negative MAE skill and depended entirely on five winners. The exact information unit is retired without feature, threshold, stop, risk or leverage rescue. `2024H1` is seen evidence and cannot be called fresh independent OOS for a modified Donchian strategy.

## Cumulative strategy ranking

1. ML UTC08-15 XRP state machine — `0.223030%`/day at 24 bp; 58 trades; positive exact winner-removal reroute.
2. Donchian all-breakout — `0.0700189%`/day at 24 bp; winner-removal failure.
3. Donchian after-loser — `0.0631845%`/day at 24 bp; winner-removal failure.
4. 2024H1 HGBT-filtered Donchian all-breakout — `0.0387317%`/day at 24 bp; negative MAE skill and negative winner-removal path.
5. CME gap competing-risk ML — `0.0334850%`/day at 24 bp; negative median and winner concentration.
6. Bybit liquidity-mass rejection — `0.0118550%`/day at 12 bp; 23 trades and complete top-five concentration.
7. 08:00 option-settlement SMT — `0.0099556%`/day at 18 bp; 12 trades.
8. Bybit MMXM lifecycle — `0.00575058%`/day at 12 bp; negative median and losing second half.
9. KRW-relative regional SMT reversal — `0.00487483%`/day at 12 bp; two trades.
10. Liquidation exhaustion reversal — `0.00358316%`/day at 18 bp; sparse and winner-removal failure.

All remain below the 1% reference and none has deployment authority. The Donchian HGBT result is ranked for cumulative comparison but receives no research protection.

## Selection and validation boundary

The current first-place base model and hold/switch policy were selected on 2023. Each half-year refit is causal, but the session/asset/side/threshold filter was selected after observing the full 2024-2025 path. The result is selected development, not sealed OOS. The forward boundary is frozen at `2025-12-31 23:59:59 UTC`; official 2026H1 has not been opened.

Fixed leverage is not used to inflate the rank. On the same path, 4x reaches only about `0.713%/day` with `97.5%` MDD and liquidation begins near `4.05x`. The unlevered one-times path is the ranking metric.

## Current objective

Do not protect or polish the new first place. It is still about `4.48x` short of the 1% daily-growth reference. Reconstruct the unchanged selected route under exact Bybit BBO/depth, historical funding, capacity, marked NAV and liquidation distance, then freeze the implementation before opening official 2026H1 once.

External forced-flow and inventory-transfer ML sources continue in parallel because exact replay alone cannot close the remaining objective gap.

## Next exact action

1. Reconstruct exact Bybit hourly BBO/depth, funding, capacity and liquidation-distance inputs for `UTC08-15 / XRP / 1.25` without changing its model or filter.
2. Verify the same 2024-2025 path under exact Bybit execution and continuous marked NAV.
3. Freeze code and open official 2026H1 once; insert the outcome immediately whether it exceeds or loses the current first place.
4. Consume stablecoin issuance and Uniswap inventory-transfer source gates; a source pass proceeds to the frozen ML screen and immediate sequential evaluation, while a failure closes the route.
5. Do not return to Donchian or generic completed-bar parameter grids.

Updated: 2026-07-26 22:34 KST
