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

It remains first only because it has the highest recorded after-cost geometric growth among current-contract-compatible paths. It is not close to the project objective: the 12-bp path still requires approximately `11.10x` more daily growth, winner removal destroys the account, the source is a Binance proxy, funding and exact Bybit BBO/depth are absent, 2024+ is unopened, and the route is non-ML.

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

## Sequential 2024-2026 research contract

The five official half-years are sequential research intervals, not one final block kept sealed indefinitely.

- `2024H1` is the first official test and uses only information available through `2023-12-31`.
- A pre-2024 candidate that is genuinely promising is evaluated in `2024H1` immediately; OOS purity is not used to postpone the test.
- After `2024H1` is observed, its result may guide a revised rule fixed with information available through `2024-06-30` for `2024H2`.
- The same causal progression applies to every later half-year while NAV remains one continuous account path.
- A period already used for revision or selection is never relabeled as a new independent final OOS for the revised strategy.
- If a result is structurally far from the objective, research changes alpha or payoff rather than preserving unused official periods or adding defensive pre-gates.

Any active claim that still describes one frozen continuous `2024-01-01` through `2026-06-30` replay must be corrected before opening official outcomes.

## Newly completed and retired work

- Direct after-cost utility ML: the frozen calibration scale became zero; confirmation predictions were constant zero and the account made no trades. Development, risk search and official periods stayed closed.
- Path-continuity first-passage ML: model AUC and Brier were worse than structural distance; 264 development trades lost `54.49% / 64.14% / 71.93%` at 12/18/24 bps and winner removal worsened the loss.
- OKX spot-swap consensus relay: only `116 / 67 / 8` train/calibration/confirmation events; the population gate failed before model fitting.
- Cross-venue fair-value maker: confirmation had zero conservative queue fills and fit gross returns were far below even 12-bp cost.
- Aave liquidation source: canonical identities and historical block access passed, but keyless archive endpoints could not deliver the bounded historical `LiquidationCall` logs. This is source unavailability, not negative alpha evidence.

None changes the cumulative strategy order. Failed economic dependencies receive no sign flip, threshold, model, risk or leverage rescue.

## Active highest-information work

- `CLM-20260726-2110-ML-DONCHIAN-STRUCTURAL-001` / PR #194: one ML utility filter on the fixed highest-growth structural breakout. Its official-period contract must open `2024H1` first rather than replay all of 2024-2026 as one frozen block.
- `CLM-20260726-2058-ML-HL-LIQUIDATION-001` / PR #191: explicit finalized Hyperliquid liquidation forced flow; source gate first, then one pooled structural first-passage model.
- `CLM-20260726-2115-ML-XVENUE-PRESHOCK-MAKER-001`: place before rather than after an external shock, with actual queue occupancy and structural cancellation.
- `CLM-20260726-2045-ML-COMPRESSION-FVG-001`: one state-defined compression-to-expansion ML route with structural exits.
- `CLM-20260726-2110-ML-STABLECOIN-ISSUANCE-001` / PR #189: explicit stablecoin mint/burn liquidity-supply source gate.
- `CLM-20260726-2135-ML-SWEEP-BREAKER-001`: causal sweep, MSS, breaker/FVG retest and one ML target-first estimate.

These are not protected. A positive hard-valid result is inserted immediately; a negative result is retired immediately.

## Current blockers

The first two ranks collapse when large winners are removed. CME gap is also winner- and Q4-concentrated. The remaining positive paths are sparse or regime-unstable. No candidate has survived a causal `2024H1` Bybit evaluation with realistic funding, execution and winner-removal robustness, and the leading strategy is still non-ML.

## Current objective

Maximize realistic after-cost account growth. Do not tune or protect the Donchian benchmark merely because it is first. Use one high-information test of its fixed structure, while prioritizing explicit forced-flow, inventory-transfer and pre-positioned execution sources that can materially exceed the present growth scale.

## Next exact action

1. Correct PR #194 before any official outcome so a passing 2023 path opens only `2024H1`; later half-years are separately fixed using only then-available information.
2. Consume the Hyperliquid liquidation source gate and open its frozen ML screen immediately on a pass; close only the transport on a source failure.
3. Consume pre-shock maker, stablecoin issuance, compression-FVG and sweep-breaker results as soon as decision-ready.
4. If no route produces a materially larger, winner-removal-positive cost-sized edge, change the information source or payoff again rather than expanding the current rank-one family.

Updated: 2026-07-26 21:41 KST
