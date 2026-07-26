# Current state

- revision: 20
- phase: ACTIVE_RESEARCH
- current first place: `FIRST-20260726-ML-DONCHIAN-HGBT-2024H1-24BPS`
- first-place stage: `OFFICIAL_2024H1_SEQUENTIAL_BINANCE_PROXY_RETIRED_WINNER_CONCENTRATED`
- target_status: `NOT_MET`
- live_order_permission: none
- repository: `umtong/SMC_ICT_2_LIVE`

## Current first place

The current first place is the frozen pooled HGBT Donchian accept/flat route from `RES-20260726-ML-DONCHIAN-2024H1-SEQUENTIAL-001`.

- information cutoff: `2023-12-31 23:59:59 UTC`
- first official interval: `2024H1`
- 24-bps geometric daily growth: `0.0387317%`
- 24-bps total return: `+7.3021%`
- completed trades: `24`
- PF: `1.8712`
- MDD: `10.17%`
- median completed trade: `-50bp`
- top-five positive-PnL share: `100%`
- exact winner-removal return: `-7.6610%`
- official-period MAE skill versus constant: `-1.6897%`
- target gap: `0.961268 percentage points per UTC calendar day`
- required growth multiple: approximately `25.82x`

It is first only because it is the strongest recorded account path whose complete route was frozen before the interval under the current sequential contract. It is not an active improvement target: the information unit is retired because the model was baseline-inferior, the median trade was negative and all positive PnL came from five winners.

Rank does not determine research priority.

## UTC state-machine correction and retirement

The former first place `RES-20260726-ML-HOURWEEK-XRP-001` recorded `0.223030%/day` at 24bp, but its 720 session/asset/side/threshold routes were selected after observing the complete 2024-2025 development path. It is retained as a development diagnostic, not an active causal strategy candidate.

To apply the required sequence correctly:

1. The base Ridge model and KEEP/SWITCH/FLAT logic were kept unchanged.
2. All 720 filters were selected on `2023H2` only.
3. The frozen winner was all UTC hours, long-only, BTCUSDT/SOLUSDT/XRPUSDT, threshold multiplier `0.75`.
4. The system was frozen at `2023-12-31` and 2024H1 was opened immediately.

Pre-2024, the selected path looked strong: `0.522298%/day` at 24bp, 42 trades, PF 3.5678, MDD 21.92%, positive median and positive exact winner-removal return.

Official 2024H1 invalidated the alpha:

- 12bp: `+0.011545%/day`, but negative median and negative exact winner-removal return
- 18bp: `-0.014829%/day`
- 24bp: `-0.041195%/day`, `-7.2247%` total, 80 trades, MDD 37.00%, median `-0.6460%`
- 24bp Q1 / Q2: `+28.39% / -27.74%`
- exact winner-removal: `-12.0168%`, `-0.070319%/day`

The entire hourweek/session/asset/side/threshold family is retired. 2024H2 through 2026H1 remain unopened for this family. No adjacent filter, feature, risk or leverage rescue is permitted.

## Active causal strategy ranking

1. Official 2024H1 frozen HGBT Donchian — `0.0387317%/day` at 24bp; retired and winner-dependent.
2. CME gap competing-risk ML — `0.0334850%/day` at 24bp; pre-2024 proxy, negative median and concentrated.
3. Bybit liquidity-mass rejection — `0.0118550%/day` at 12bp; 23 trades and complete top-five concentration.
4. Official 2024H1 unfiltered Donchian — `0.0100516%/day` at 24bp.
5. 08:00 option-settlement SMT — `0.0099556%/day` at 18bp; 12 trades.
6. Bybit MMXM lifecycle — `0.00575058%/day` at 12bp.
7. KRW-relative regional SMT reversal — `0.00487483%/day` at 12bp; two trades.
8. Liquidation exhaustion reversal — `0.00358316%/day` at 18bp.

All remain structurally far below 1%. None has deployment authority. Rank creates no incumbency protection.

## Current objective

Do not tune Donchian or UTC time filters. Their first official sequential evidence is structurally distant.

The only active alpha directions are materially distinct information sources capable of creating cost-sized order pressure before Bybit delivery:

1. causally confirmed USDT/USDC issuance and destruction;
2. completed Uniswap WETH-stable inventory transfer and subsequent hedge relay;
3. finalized account liquidation or joint liquidation/OI/order-book state.

Each route follows the same minimal sequence: one information unit, one ML model, one structural action rule, immediate 2024H1 evaluation once frozen with information through 2023-12-31, then causal half-year continuation only while the observed performance remains structurally capable of closing the target gap.

Updated: 2026-07-26 23:00 KST
