# Current state

- revision: 14
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
- 12-bps geometric daily growth: `0.0900854%`
- 18-bps geometric daily growth: `0.0794137%`
- 24-bps geometric daily growth: `0.0700189%`
- 1% target gap at 12 bps: `0.9099146 percentage points per UTC calendar day`
- 12/18/24-bps total return: `+38.9111% / +33.6087% / +29.1080%`
- trades: `99`
- 12/24-bps PF: `1.79595 / 1.62745`
- 12/24-bps MDD: `9.7194% / 9.8554%`
- median account return: `-50 bps`
- win rate: `20.20%`
- top-five positive-PnL share: `65.11% / 64.22%`
- top-10%-winner-removed return: `-26.29% / -26.95%`
- median holding time: `19 hours`
- maximum used leverage: `0.875x / 0.723x`
- exits: `25` channel exits, `74` ATR stops

It is first because it has the highest recorded after-cost geometric growth among current-contract-compatible paths. It is not a solution: the source is a Binance proxy, funding and exact Bybit BBO/depth are absent, 2024+ is unopened, winner removal destroys the account, and the route is non-ML.

Rank does not determine research priority.

## Cumulative strategy ranking

1. Donchian all-breakout `a70626d9e484285f2cb4|all` — `0.0900854%`/day at 12 bps; 99 trades; winner-removal failure.
2. Donchian after-loser `a70626d9e484285f2cb4|after_loser` — `0.0829996%`/day at 12 bps; 89 trades; winner-removal failure.
3. CME gap competing-risk ML `da1b9e2861d6b396b81e` — `0.0459425%`/day at 12 bps; 38 trades; proxy, negative median and Q4 concentration.
4. Bybit liquidity-mass rejection `142f8501fcc7874fd6d2` — `0.0118550%`/day at 12 bps; 23 trades; all positive PnL in five winners.
5. 08:00 option-settlement SMT `951df185862595e1` — `0.0099556%`/day at 18 bps; 12 trades; proxy and winner-removal failure.
6. Bybit MMXM lifecycle `80d3e98612ce67650e4c` — `0.00575058%`/day at 12 bps; 296 trades; negative median and losing second half.
7. KRW-relative regional SMT reversal `297bb96ecbf036bb` — `0.00487483%`/day at 12 bps; two trades; winner-removal failure.
8. Liquidation exhaustion reversal `0c0b773a5be4eab4` — `0.00358316%`/day at 18 bps; 19 development trades; fit sign reversal and winner-removal failure.

All eight are below the 1% reference and none has deployment authority.

## Removed from the active ranking

- dynamic state-exit: `maximum_hold_bars=96` and default eight-hour timeout exit.
- aligned continuation: `maximum_holding_minutes` and scheduled horizon close.
- spot-perpetual overshoot reversal: `candidate.hold`, `timeout_i` and timeout exit.
- DVOL low-VRP continuation: `maximum_hold_bars`.
- high-resistance sweep: durable result status `INVALID` and `hold=48`.
- fragmented-flow reversal: `hold_minutes=30`, only four trades and negative winner-removal path.

These historical results remain recorded but cannot rank under the fixed no-elapsed-time-liquidation contract.

## Ranking policy

- A result-local label such as `fatal screen` or `non-rank-eligible` does not erase a current-contract-compatible account path from the project cumulative ranking.
- Incomplete cost, data or execution comparability is represented by a provisional rank and explicit comparison confidence.
- A prohibited elapsed-time liquidation is a contract failure and cannot be offset by higher return.
- Below 1%, higher sustainable after-cost geometric growth and the smaller target gap rank ahead.
- Economic-gate status, validation stage, deployment status and research priority remain separate from rank.
- A new positive hard-valid result is inserted immediately; a newly discovered contract failure removes the candidate immediately.

## Work stopped and retired

The fixed 2024 portfolio combining the invalid dynamic component with aligned continuation remains closed before any 2024 strategy outcome.

Coinbase spot-flow ML is closed as `SOURCE_UNAVAILABLE`; no market row or model outcome existed. Bybit mark/index raid-acceptance ML is a complete negative result. Neither route receives threshold, risk or leverage rescue.

## Active high-information ML work

- four-asset direct after-cost utility regression with turnover-aware `KEEP / SWITCH / FLAT` actions;
- OKX spot-swap consensus and OI sponsorship relay into delayed executable Bybit BBO;
- path-continuity structural first-passage ML;
- Aave V2/V3 `LiquidationCall` forced-flow source gate and conditional ETH ML screen.

These paths are prioritized because they can create cost-sized information before Bybit delivery, not because of the current rank.

## Current blockers

The first two ranks collapse when large winners are removed. CME gap is also winner- and Q4-concentrated. The remaining positive paths are sparse or regime-unstable. No candidate has survived realistic sequential 2024-2026 Bybit execution, funding, winner removal and regime changes, and the leading routes are not a deployable ML system.

## Current objective

Maximize realistic after-cost account growth and search for a materially stronger information source/payoff. Do not tune or protect the Donchian benchmark. Finish the active direct-utility, OKX, path-continuity and Aave paths; insert any superior result immediately and retire any failed dependency immediately.

## Next exact action

1. Complete the direct-utility gap-boundary correction without imputation and run its frozen chronological screen.
2. Consume the OKX and path-continuity results as soon as immutable account paths exist.
3. Finish the Aave source gate; pass opens the frozen ML screen, failure retires the source.
4. If all fail, open a materially new forced-flow or inventory-transfer source rather than another completed-bar parameter family.

Updated: 2026-07-26 21:05 KST
