# Current state

- revision: 15
- phase: ACTIVE_RESEARCH
- current first place: `FIRST-20260726-DONCHIAN-ALL-A70626D9E484`
- first-place stage: `PRELIMINARY_CAUSAL_BINANCE_PROXY`
- target_status: `NOT_MET`
- live_order_permission: none
- repository: `umtong/SMC_ICT_2_LIVE`

## Current first place

The provisional first place is the Donchian all-breakout route `a70626d9e484285f2cb4|all` from `RES-20260726-DONCHIAN-DEPENDENCE-001`.

- completed 60-minute channel; entry lookback 96, exit channel 48
- exits: ATR stop or completed channel exit; no elapsed-time liquidation
- 12/18/24-bps geometric daily growth: `0.0900854% / 0.0794137% / 0.0700189%`
- 1% target gap at 12 bps: `0.9099146 percentage points per UTC calendar day`
- 12/18/24-bps total return: `+38.9111% / +33.6087% / +29.1080%`
- trades: `99`
- 12/24-bps PF: `1.79595 / 1.62745`
- 12/24-bps MDD: `9.7194% / 9.8554%`
- median account return: `-50 bps`; win rate: `20.20%`
- top-five positive-PnL share: `65.11% / 64.22%`
- top-10%-winner-removed return: `-26.29% / -26.95%`
- median holding time: `19 hours`
- maximum used leverage: `0.875x / 0.723x`
- exits: `25` channel exits, `74` ATR stops

It is first only because it has the highest recorded after-cost geometric growth among current-contract-compatible paths. It is not a solution or a protected research direction: the source is a Binance proxy, funding and exact Bybit BBO/depth are absent, 2024+ is unopened, winner removal destroys the account, and the route is non-ML.

## Cumulative strategy ranking

1. Donchian all-breakout `a70626d9e484285f2cb4|all` — `0.0900854%`/day at 12 bps; 99 trades; winner-removal failure.
2. Donchian after-loser `a70626d9e484285f2cb4|after_loser` — `0.0829996%`/day at 12 bps; 89 trades; winner-removal failure.
3. CME gap competing-risk ML `da1b9e2861d6b396b81e` — `0.0459425%`/day at 12 bps; 38 trades; proxy, negative median and Q4 concentration.
4. Bybit liquidity-mass rejection `142f8501fcc7874fd6d2` — `0.0118550%`/day at 12 bps; 23 trades; all positive PnL in five winners.
5. 08:00 option-settlement SMT `951df185862595e1` — `0.0099556%`/day at 18 bps; 12 trades; proxy and winner-removal failure.
6. Bybit MMXM lifecycle `80d3e98612ce67650e4c` — `0.00575058%`/day at 12 bps; 296 trades; negative median and losing second half.
7. KRW-relative regional SMT reversal `297bb96ecbf036bb` — `0.00487483%`/day at 12 bps; two trades; winner-removal failure.
8. Liquidation exhaustion reversal `0c0b773a5be4eab4` — `0.00358316%`/day at 18 bps; 19 development trades; fit sign reversal and winner-removal failure.

All eight are below the 1% reference and none has deployment authority. Rank creates no incumbency protection.

## Removed or unranked completed work

- Dynamic state-exit, aligned continuation, spot-perpetual overshoot reversal, DVOL low-VRP continuation, high-resistance sweep and fragmented-flow reversal remain outside the ranking because of prohibited elapsed-time exits or hard invalidity.
- Direct after-cost utility ML, `RES-20260726-ML-DIRECT-UTILITY-001`: the frozen calibration scale was `0`, untouched confirmation prediction variance was `0`, error was worse than a constant baseline, and 12/18/24-bp authorized trades were `0 / 0 / 0`. Development and risk/leverage search remained unopened; exact information unit retired.
- Path-continuity first-passage ML: HGBT AUC `0.571277` versus structural-distance baseline `0.635450`; 24-bp account return `-71.93%`; exact route retired.
- OKX spot-swap/OI consensus relay: train/calibration/confirmation event counts `116 / 67 / 8`; no model; exact sparse unit retired.
- Aave V2/V3 liquidation forced-flow: keyless archival log transport unavailable before any price, label, model or PnL; source route closed without an alpha conclusion.
- Coinbase spot-flow and mark/index raid-acceptance ML remain closed under their recorded source or economic failures.

Failed candidates receive no adjacent feature, threshold, calibration, stop, risk or leverage rescue.

## Active high-information ML work

- Stablecoin issuance/destruction source gate, PR #189: actual Ethereum USDT/USDC mint and burn events, followed conditionally by one frozen BTC/ETH first-passage HGBT.
- Uniswap WETH-stable inventory-transfer source gate, PR #190: actual WETH/USDC/USDT pool inventory deltas, followed conditionally by one frozen ETH hedge-relay HGBT.

These sources are prioritized because they observe external inventory creation or completed inventory transfer before potential Bybit delivery. They are not extensions of Donchian or completed-bar setup grids.

## Current blockers

The first two ranks collapse when large winners are removed. CME gap is also winner- and Q4-concentrated. The remaining positive paths are sparse or regime-unstable. No candidate has survived realistic sequential 2024-2026 Bybit execution, funding, winner removal and regime changes, and the leading routes are not a deployable ML system.

## Current objective

Maximize realistic after-cost account growth and replace the benchmark with a materially stronger ML information source or payoff. Do not tune or protect the Donchian benchmark. Consume each source gate immediately: a pass opens the frozen economic screen; a failure closes the route without polishing it.

## Next exact action

1. Finish the Uniswap WETH-stable inventory-transfer source gate; on pass run the frozen conditional ML screen immediately, on failure close the source route.
2. Finish the full-chronology stablecoin issuance/burn source gate under the same pass-or-close rule.
3. Insert any superior hard-valid account path into the cumulative ranking immediately.
4. If both external-inventory routes fail, select a materially different forced-flow source rather than returning to completed-bar parameter families.

Updated: 2026-07-26 21:40 KST
