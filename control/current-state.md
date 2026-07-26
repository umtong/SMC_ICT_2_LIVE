# Current state

- revision: 19
- phase: ACTIVE_RESEARCH
- current first place: `FIRST-20260726-ML-HOURWEEK-XRP-0815-125`
- first-place stage: `PROVISIONAL_CAUSAL_SEQUENTIAL_REFIT_SELECTED_DEVELOPMENT_BINANCE_PROXY`
- target_status: `NOT_MET`
- live_order_permission: none
- repository: `umtong/SMC_ICT_2_LIVE`

## Current first place

The provisional first place is the causal Ridge UTC-state route `UTC08-15 / BOTH / XRPUSDT / threshold 1.25` from `RES-20260726-ML-HOURWEEK-XRP-001`.

- model: one pooled Ridge using completed trend, volatility, quote-volume, taker-flow, cross-sectional state and asset-specific UTC hour-of-week/hour-of-day interactions
- update rule: before each 2024-2025 half-year, refit the model and 95th-percentile calibration threshold using only information available before that block
- entry: XRPUSDT at the next hourly open during UTC 08:00-15:59 when absolute expected return is at least 1.25 times the prior-only calibrated threshold
- exit: signed expected edge is no longer positive or a stronger eligible alternative takes the one global slot
- elapsed-time liquidation: none
- 12 / 24 bps geometric daily growth: `0.232573% / 0.223030%`
- 24-bps ending NAV / total return: `5.0964x / +409.639%`
- 24-bps target gap: `0.776970 percentage points per UTC calendar day`
- 24-bps target fraction: `22.3030%`
- 24-bps trades / PF / MDD / median trade: `58 / 4.8808 / 25.81% / +2.1499%`
- long / short trades: `51 / 7`
- top-five positive-PnL share: `33.65%`
- 2024H1 / 2024H2 / 2025H1 / 2025H2 return: `+1.03% / +159.93% / +75.77% / +10.42%`
- exact top-10%-of-all-trades event removal before slot rerouting: `3.6051x NAV`, `0.175579%/day`, PF `4.0107`, all four half-years positive
- 72-bps stress: `0.184867%/day`
- 96-bps stress: `0.165791%/day` overall, with slightly negative 2025H2

It replaced the Donchian benchmark because its 24-bps growth is 3.185x higher, its median trade is positive, concentration is lower, and the fully rerouted winner-removal path remains strongly positive. Rank does not protect it.

## Selection and validation boundary

The base model and KEEP/SWITCH policy were selected on 2023. The half-year refits are causal within each block, but the 720 session/asset/side/threshold routes were selected after observing the complete 2024-2025 development path. Therefore the account is selected development, not sealed 2024-2025 OOS.

The forward boundary is frozen at `2025-12-31 23:59:59 UTC`. Official 2026H1 remains unopened. The current account uses Binance USD-M hourly data, an adverse unsigned funding proxy and one-times NAV notional. Exact Bybit BBO/depth, historical funding, partial fills, capacity, margin and liquidation distance remain unverified.

Fixed leverage is not the route's alpha. On the unchanged proxy path, 4x reaches only about `0.713%/day` with `97.5%` MDD, and liquidation begins near `4.05x`. Ranking uses the one-times path.

## Official 2024H1 Donchian decision

`RES-20260726-ML-DONCHIAN-2024H1-SEQUENTIAL-001` opened 2024H1 immediately using a system frozen with information through 2023-12-31.

At 24 bps:
- unfiltered Donchian: `0.010052%/day`, `+1.8461%`, 49 completed trades, PF `1.1090`, MDD `12.70%`
- frozen pooled HGBT filter: `0.038732%/day`, `+7.3021%`, 24 completed trades, PF `1.8712`, MDD `10.17%`
- HGBT median completed trade: `-50bp`
- top-five positive-PnL share: `100%`
- exact winner-removal reroute: `-7.6610%`, `-0.043784%/day`
- official-period MAE skill versus the constant baseline: `-1.6897%`

The result is hard-valid sequential evidence but structurally far below the objective and entirely winner-dependent. The exact HGBT information unit is retired without feature, threshold, stop, risk or leverage rescue. 2024H1 is now seen and cannot be relabeled fresh independent OOS for a modified strategy.

## Cumulative strategy ranking

1. ML UTC08-15 XRP state machine — `0.223030%/day` at 24 bps; positive exact winner-removal path; selected development.
2. Donchian all-breakout `a70626d9e484285f2cb4|all` — `0.0700189%/day` at 24 bps; pre-2024 Binance proxy; winner-removal failure.
3. Donchian after-loser `a70626d9e484285f2cb4|after_loser` — `0.0631845%/day` at 24 bps; winner-removal failure.
4. Official 2024H1 Donchian HGBT accept/flat — `0.0387317%/day` at 24 bps; retired; winner-removal negative.
5. CME gap competing-risk ML — `0.0334850%/day` at 24 bps; negative median and winner concentration.
6. Bybit liquidity-mass rejection — `0.0118550%/day` at 12 bps; 23 trades and complete top-five concentration.
7. 08:00 option-settlement SMT — `0.0099556%/day` at 18 bps; 12 trades.
8. Bybit MMXM lifecycle — `0.00575058%/day` at 12 bps; negative median and losing second half.
9. KRW-relative regional SMT reversal — `0.00487483%/day` at 12 bps; two trades.
10. Liquidation exhaustion reversal — `0.00358316%/day` at 18 bps; sparse and winner-removal failure.

All remain below 1%. None has deployment authority, and rank creates no incumbency protection.

## Current objective

The new first place is still approximately 4.48x short of the 1% daily-growth reference. The immediate improvement path is not fixed leverage or another filter tournament.

1. Reconstruct exact Bybit hourly BBO/depth, funding, capacity, margin and liquidation-distance inputs for the frozen UTC08-15 XRP route.
2. Replay the unchanged 2024-2025 route with continuous marked NAV and realistic Bybit execution.
3. If cost-surviving alpha remains, freeze the execution/account contract and open official 2026H1 once.
4. Continue stablecoin issuance/destruction, Uniswap WETH-stable inventory transfer and finalized Hyperliquid liquidation ML in parallel because they can add materially distinct information.
5. Retire any structurally distant result immediately; do not return to Donchian or generic completed-bar parameter grids.

Updated: 2026-07-26 22:26 KST
