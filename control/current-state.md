# Current state

- revision: 22
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

The former first place `RES-20260726-ML-HOURWEEK-XRP-001` recorded `0.223030%/day` at 24bp, but its 720 session/asset/side/threshold routes were selected after observing the complete 2024-2025 development path. It remains a development diagnostic, not an active causal strategy candidate.

The full filter family was selected again using 2023H2 only, frozen at `2023-12-31`, and opened immediately on 2024H1. The frozen all-hours, long-only BTCUSDT/SOLUSDT/XRPUSDT route lost at 18bp and 24bp. At 24bp it returned `-7.2247%`, grew `-0.041195%/day`, made 80 trades, suffered 37.00% MDD and had a `-0.6460%` median trade. Exact winner-removal returned `-12.0168%` and `-0.070319%/day`.

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

## Closed external-inventory source dependencies

`RES-20260726-ML-UNISWAP-INVENTORY-SOURCE-SEMANTICS-001` closes the cumulative Hugging Face USDC/WETH source before market outcomes. Its `USDC` and `WETH` columns are cumulative unsigned volumes, not pool balances or signed `amount0/amount1` Swap flow, so WETH purchase versus sale direction cannot be reconstructed causally. The route may reopen only with canonical signed V3 Swap events or an equivalent immutable source.

`RES-20260726-ML-BINANCE-COINM-LIQ-SOURCE-COVERAGE-001` closes the continuous 2021-2023 Binance COIN-M liquidationSnapshot dependency before market outcomes. Official S3 listing evidence shows BTCUSD_PERP and ETHUSD_PERP archives begin only on `2023-06-25`; requested-period coverage is `17.0776%` and `16.9863%`, far below the frozen 80% minimum. No price, label, model, action, trade, PnL, risk/leverage search or official interval opened.

These are source-semantic or source-coverage results, not negative alpha evidence against a future complete signed inventory source.

## Sole active high-information ML work

Only one primary information unit remains active: corrected Ethereum USDT `Issue/Redeem` plus USDC zero-address `Transfer` supply shocks.

The source decision covers every month in 2021-2023, requires 12-block availability with 64-block stress, both tokens, at least 120 unique events and at least 24 event-bearing months. A source PASS opens exactly one strict-causal BTC/ETH HGBT account system. Features stop at the last fully completed minute at the finalized event second; the next-minute open is execution only; unresolved stage-boundary exposure is marked rather than synthetically exited.

A cost-surviving pre-2024 survivor is frozen using information through `2023-12-31` and opens official 2024H1 immediately. Source or economic failure retires the exact dependency and requires a new alpha source rather than adjacent tuning.

## Current objective and next exact action

Do not tune Donchian, UTC filters, unsigned Uniswap volumes or incomplete liquidation snapshots. Consume the strict-causal stablecoin source and economic decision now.

- Source PASS opens the already-frozen pre-2024 model/account stage in the same execution.
- A positive non-concentrated survivor opens official 2024H1 immediately.
- Source or economic failure closes the exact route without feature, threshold, target, stop, risk or leverage rescue.
- Any superior hard-valid account path is inserted into the cumulative ranking immediately.
- Growth above 1% is retained at full strength; 1% is never treated as a ceiling.

Updated: 2026-07-27 00:39 KST
