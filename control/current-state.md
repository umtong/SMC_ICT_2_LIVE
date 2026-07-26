# Current state

- revision: 16
- phase: ACTIVE_RESEARCH
- current first place: `FIRST-20260726-DONCHIAN-ALL-A70626D9E484`
- first-place stage: `PRELIMINARY_CAUSAL_BINANCE_PROXY_WITH_OFFICIAL_2024H1_SEQUENTIAL_EVIDENCE`
- target_status: `NOT_MET`
- live_order_permission: none
- repository: `umtong/SMC_ICT_2_LIVE`

## Current first place

The provisional first place remains Donchian all-breakout `a70626d9e484285f2cb4|all` from `RES-20260726-DONCHIAN-DEPENDENCE-001`, now compared at the normalized 24-bp cost path.

- 24-bp geometric daily growth in 2023: `0.0700189%`
- 1% target gap: `0.9299811 percentage points per UTC calendar day`
- target fraction: `7.00189%`
- required growth multiple: approximately `14.28x`
- 24-bp total return: `+29.1080%`
- completed trades: `99`
- PF: `1.62745`
- MDD: `9.8554%`
- median account return: `-50 bp`
- win rate: `20.20%`
- top-five positive-PnL share: `64.22%`
- top-10%-winner-removed return: `-26.9469%`
- exits: `25` completed-channel exits and `74` ATR stops; no elapsed-time liquidation

It remains first only because its recorded normalized 24-bp growth is the highest among current-contract-compatible paths. It is not a solution or a protected direction. It uses Binance completed bars rather than exact Bybit BBO/depth, omits historical funding, is non-ML and collapses after large winners are removed.

Rank does not determine research priority.

## First official sequential interval opened

`RES-20260726-ML-DONCHIAN-2024H1-SEQUENTIAL-001` froze one pooled HGBT accept-or-flat filter using only information available through `2023-12-31` and opened `2024H1` as the first official sequential research interval.

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

The filter improved the unchanged 2024H1 baseline but remained structurally far below the 1% objective, had negative MAE skill and depended entirely on five winners. The exact model, feature and payoff information unit is retired without threshold, feature, stop, risk or leverage rescue. `2024H1` is now seen evidence and cannot be presented as fresh independent OOS for a modified strategy.

## Cumulative strategy ranking

1. Donchian all-breakout `a70626d9e484285f2cb4|all` — `0.0700189%`/day at 24 bp; 2023 proxy, severe winner-removal failure and weak 2024H1 continuation.
2. Donchian after-loser `a70626d9e484285f2cb4|after_loser` — `0.0631845%`/day at 24 bp; severe winner concentration.
3. 2024H1 HGBT-filtered Donchian all-breakout — `0.0387317%`/day at 24 bp; official sequential interval, negative MAE skill and negative winner-removal path.
4. CME gap competing-risk ML `da1b9e2861d6b396b81e` — `0.0334850%`/day at 24 bp; proxy, negative median and Q4 concentration.
5. Bybit liquidity-mass rejection `142f8501fcc7874fd6d2` — `0.0118550%`/day at 12 bp; 23 trades and all positive PnL in five winners.
6. 08:00 option-settlement SMT `951df185862595e1` — `0.0099556%`/day at 18 bp; 12 trades and winner-removal failure.
7. Bybit MMXM lifecycle `80d3e98612ce67650e4c` — `0.00575058%`/day at 12 bp; negative median and losing second half.
8. KRW-relative regional SMT reversal `297bb96ecbf036bb` — `0.00487483%`/day at 12 bp; two trades and winner-removal failure.
9. Liquidation exhaustion reversal `0c0b773a5be4eab4` — `0.00358316%`/day at 18 bp; fit sign reversal and winner-removal failure.

All ranked paths remain below the 1% reference and none has deployment authority. The newly inserted official 2024H1 path is ranked because the ranking must record comparative results, not because it should receive more research budget.

## Retired or unavailable work

- The Donchian HGBT filter is retired after the official 2024H1 result.
- Dynamic state-exit, aligned continuation, spot-perpetual overshoot reversal, DVOL low-VRP continuation, high-resistance sweep and fragmented-flow reversal remain outside ranking because of prohibited elapsed-time exits or hard invalidity.
- Direct after-cost utility ML, path-continuity ML and OKX consensus are negative or event-scarce under their frozen contracts.
- Aave and Coinbase routes closed before economic outcomes because the required historical source transport was unavailable.
- Failed candidates receive no adjacent feature, threshold, calibration, stop, risk or leverage rescue.

## Active high-information ML work

- Stablecoin issuance/destruction, PR #189: finalized Ethereum USDT/USDC mint and burn events, followed by one frozen BTC/ETH first-passage model and immediate sequential `2024H1` evaluation after the pre-2024 rule is frozen.
- Uniswap WETH-stable inventory transfer, PR #190: completed pool inventory deltas, followed by one frozen ETH hedge-relay model and the same immediate sequential `2024H1` contract.

These routes observe external inventory creation or completed inventory transfer before potential Bybit delivery. They are not extensions of the retired Donchian or completed-bar setup families.

## Current blockers

No candidate has survived realistic sequential 2024-2026 Bybit execution, funding, winner removal and regime changes. The current first place and the new official 2024H1 result both depend on a small number of large winners. The project still lacks a cost-sized ML information unit with repeatable positive median expectancy and a structural path toward 1% daily geometric growth.

## Current objective

Maximize realistic after-cost account growth and replace the benchmark with a materially stronger information source or payoff. Consume each active source gate immediately. A pass freezes the complete pre-2024 strategy and opens 2024H1 without an added purity-preservation gate. A failure closes the route and moves to a different alpha source.

## Next exact action

1. Consume the first decision-ready result from stablecoin issuance or Uniswap inventory transfer.
2. On source pass, run the frozen pre-2024 model and open `2024H1` immediately after the strategy, sizing and execution rules are fixed using information through `2023-12-31`.
3. Retire the route if `2024H1` remains structurally far from 1%; otherwise use only information available through `2024-06-30` to freeze the `2024H2` version.
4. Insert every superior hard-valid account path into the cumulative ranking immediately.

Updated: 2026-07-26 21:58 KST
