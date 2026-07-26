# Current state

- revision: 16
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

It is first only because it has the highest recorded after-cost geometric growth among current-contract-compatible paths. It is not a solution or a protected research direction: the source is a Binance proxy, funding and exact Bybit BBO/depth are absent, official 2024H1 is not yet reported, winner removal destroys the account, the route is non-ML, and the 12-bp growth is still approximately `11.10x` below the 1% reference.

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

## Official 2024-2026 sequential research contract

The official half-years are sequential research intervals, not one final block protected from observation.

- `2024H1` is the first official evaluation. A strategy fixed using information through `2023-12-31` is tested there immediately when it is the current promising candidate.
- The observed `2024H1` result is used to decide whether to retire the alpha, keep the unchanged rule, or create a later version using information available through `2024-06-30` for `2024H2`.
- The same causal progression applies to `2025H1`, `2025H2` and `2026H1`, while the project account NAV remains one continuous path.
- A half-year already observed and used for revision or selection is never described as a new independent OOS for the revised strategy.
- OOS discipline distinguishes what was known when each version was fixed; it does not justify preserving official periods while a candidate remains unevaluated.
- If an official result is structurally far from the objective, research switches alpha or payoff immediately rather than adding pre-gates or protecting unused periods.

`CLM-20260726-2139-DONCHIAN-2024H1-001` is the active official evaluation of the unchanged pre-2024 rank-one benchmark. Its result changes the next research decision but does not protect the Donchian family.

## Active high-information ML work

- Stablecoin issuance/destruction source gate, PR #189: actual Ethereum USDT/USDC mint and burn events, followed conditionally by one frozen BTC/ETH first-passage HGBT. A pre-2024 survivor opens `2024H1` immediately under the sequential contract.
- Uniswap WETH-stable inventory-transfer source gate, PR #190: actual WETH/USDC/USDT pool inventory deltas, followed conditionally by one frozen ETH hedge-relay HGBT.

These sources are prioritized because they observe external inventory creation or completed inventory transfer before potential Bybit delivery. They are not extensions of Donchian or completed-bar setup grids.

## Current blockers

The first two ranks collapse when large winners are removed. CME gap is also winner- and Q4-concentrated. The remaining positive paths are sparse or regime-unstable. No candidate has yet survived the official causal `2024H1` Bybit evaluation with realistic funding, execution and winner-removal robustness, and the leading routes are not a deployable ML system.

## Current objective

Maximize realistic after-cost account growth and replace the benchmark with a materially stronger ML information source or payoff. Do not tune or protect the Donchian benchmark. Consume each official interval and source gate immediately: a promising result advances causally, a weak economic result retires the alpha, and a source failure closes only the unavailable transport.

## Next exact action

1. Consume the unchanged Donchian `2024H1` account result as soon as `CLM-20260726-2139-DONCHIAN-2024H1-001` becomes decision-ready; if structurally weak, retire it as an improvement path and switch alpha.
2. Finish the Uniswap WETH-stable inventory-transfer source gate; on pass run the frozen conditional ML screen immediately, on failure close the source route.
3. Finish the full-chronology stablecoin issuance/burn source gate under the same pass-or-close rule, with immediate `2024H1` evaluation for a robust pre-2024 survivor.
4. Insert any superior hard-valid account path into the cumulative ranking immediately; if the external-inventory routes fail, select another materially different forced-flow source rather than returning to completed-bar parameter families.

Updated: 2026-07-26 21:51 KST
