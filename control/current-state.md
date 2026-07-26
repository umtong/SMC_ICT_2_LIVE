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
- 12/24-bps geometric daily growth: `0.232573% / 0.223030%`
- 24-bps NAV multiple and total return: `5.0964x / +409.639%`
- 1% target gap at 24 bps: `0.776970 percentage points per UTC calendar day`
- trades: `58`; PF: `4.8808`; MDD: `25.81%`; median trade: `+2.1499%`
- directions: `51` long, `7` short; mean holding time `36.31` hours
- top-five positive-PnL share: `33.65%`
- 2024H1/H2 and 2025H1/H2 returns: `+1.03% / +159.93% / +75.77% / +10.42%`
- exact top-10%-of-all-trades winner removal before slot rerouting: `3.6051x`, `0.175579%/day`, all four halves positive
- 72-bp stress: `0.184867%/day`; 96-bp stress remains profitable overall but 2025H2 is slightly negative

It replaces Donchian because its 24-bp growth is `3.185x` higher, its median trade is positive and full winner-removal rerouting remains strongly positive. It remains provisional: 720 filters were selected on the complete 2024-2025 path, market data and funding are proxies, exact Bybit BBO/depth/margin/capacity are absent, only 58 trades exist and official 2026H1 is unopened.

## Official 2024H1 sequential evidence consumed

`RES-20260726-ML-DONCHIAN-2024H1-SEQUENTIAL-001` evaluated a pre-2024 frozen Donchian HGBT filter immediately on the first official interval.

- unfiltered 24-bp growth: `0.0100516%/day`, total return `+1.8461%`, 49 completed trades
- HGBT-filtered 24-bp growth: `0.0387317%/day`, total return `+7.3021%`, 24 completed trades
- filtered PF `1.8712`, MDD `10.1656%`, median completed trade `-50bp`
- five positive winners supplied `100%` of positive PnL
- exact winner-removal reroute: `-7.6610%`, `-0.0437839%/day`
- official 2024H1 MAE skill versus a constant baseline: `-1.6897%`
- one position remained open at June 30 and was marked with hypothetical exit cost rather than forcibly closed

The result is hard-valid and independently reproduced, but economically weak and winner-dependent. The exact Donchian HGBT information unit is retired without threshold, feature, stop, risk or leverage rescue. 2024H1 is now seen sequential evidence and may not be relabeled fresh OOS for a modified Donchian strategy.

## Cumulative strategy ranking

1. ML UTC08-15 XRP state machine — `0.223030%/day` at 24 bps; 58 trades; positive exact winner-removal path.
2. Donchian all-breakout — `0.0700189%/day` at 24 bps; winner-removal failure.
3. Donchian after-loser — `0.0631845%/day` at 24 bps; winner-removal failure.
4. Official 2024H1 Donchian HGBT — `0.0387317%/day` at 24 bps; model MAE below baseline and winner-removal negative.
5. CME gap competing-risk ML — `0.0334850%/day` at 24 bps; negative median and winner concentration.
6. Bybit liquidity-mass rejection — `0.0118550%/day` at 12 bps; 23 trades and complete top-five concentration.
7. 08:00 option-settlement SMT — `0.0099556%/day` at 18 bps; 12 trades.
8. Bybit MMXM lifecycle — `0.00575058%/day` at 12 bps; negative median and losing second half.
9. KRW-relative regional SMT reversal — `0.00487483%/day` at 12 bps; two trades.
10. Liquidation exhaustion reversal — `0.00358316%/day` at 18 bps; sparse and winner-removal failure.

All remain below the 1% reference and none has deployment authority. Rank creates no incumbency protection.

## Selection, reproducibility and validation boundary

The XRP base policy was selected on 2023 and each half-year forecast is causal, but the session/asset/side/threshold filter was selected after observing all of 2024-2025. This is selected development, not sealed OOS. The forward boundary is frozen at `2025-12-31 23:59:59 UTC`.

The raw four-symbol source artifact and result/validation records are retained, but the exact portable model/account reproduction source is not yet present in canonical GitHub or linked Drive evidence. Official 2026H1 must not open until the frozen algorithm is independently reconstructed, fixed-quantity and turnover accounting are verified, and exact Bybit execution/funding/capacity/margin contracts are fixed.

Fixed leverage is not used to inflate rank. The unlevered path is the comparison metric; about 4x produces approximately `0.713%/day` with `97.5%` MDD and liquidation begins near `4.05x`.

## Current objective

Do not protect or polish the new first place. It is still about `4.48x` short of the 1% reference. The highest-information work is to harden or invalidate its claimed edge under a source-complete exact reproduction, exact Bybit replay and one frozen 2026H1 test, while continuing materially different forced-flow and inventory-transfer ML paths.

## Next exact action

1. Publish or independently reconstruct the exact `UTC08-15 / XRP / 1.25` model, filter tournament and account replay from the retained SHA-identified raw artifact.
2. Audit fixed quantity, turnover charges, mark-to-market NAV, funding, boundary positions, winner-removal rerouting and no-time-exit behavior; hard-invalidate the rank if parity cannot be reproduced.
3. Reconstruct exact Bybit 2024-2025 BBO/depth, funding, capacity and liquidation-distance inputs without changing the model/filter, then freeze the forward contract.
4. Open official 2026H1 exactly once and immediately insert, demote or retire the route.
5. Continue external forced-flow and inventory-transfer ML sources in parallel; do not return to Donchian or generic completed-bar grids.

Updated: 2026-07-26 22:38 KST
