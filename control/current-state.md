# Current state

- revision: 14
- phase: ACTIVE_RESEARCH
- current first place: `FIRST-20260726-DONCHIAN-ALL-A70626D9E484`
- first-place stage: `PRELIMINARY_CAUSAL_BINANCE_PROXY`
- target_status: `NOT_MET`
- live_order_permission: none
- repository: `umtong/SMC_ICT_2_LIVE`

## Ranking correction

The former first place, dynamic state-exit `021fbab613517a31ad98` from `RES-20260725-DYNAMIC-FACTOR-001`, remains removed from the current-contract ranking. Its immutable state-exit implementation defaults surviving trades to a finite 96-bar open, an eight-hour elapsed-time liquidation prohibited by the fixed project contract.

Merged revision 13 then contained an internal inconsistency: its durable `RESULT.json` selected the higher Donchian all-breakout comparator as first, while ranking, state and decision files selected the lower after-loser path. Revision 14 resolves that inconsistency according to the policy that incomplete comparisons receive provisional rank with disclosed uncertainty rather than silent exclusion.

## Current first place

The provisional first place is the Donchian all-breakout comparator `a70626d9e484285f2cb4|all` from `RES-20260726-DONCHIAN-DEPENDENCE-001` / PR #61.

- rule: completed 60-minute Donchian channel, entry lookback 96 and completed exit channel 48; ordinary all-breakout mode
- 12-bps geometric daily growth: `0.0900854%`
- 24-bps geometric daily growth: `0.0700189%`
- 1% target gap at 12 bps: `0.9099146 percentage points per UTC calendar day`
- target fraction at 12 bps: `9.00854%`
- target multiple still required at 12 bps: `11.10x`
- elapsed-time liquidation: none; operational exits are ATR stop or completed Donchian channel exit

Comparison confidence is `VERY_LOW`. The compact result did not preserve this comparator's complete trade ledger, total return, MDD, PF, median, win rate or concentration fields. The source is a Binance USD-M proxy, historical funding and exact Bybit execution were not replayed, no 2024 or later interval was opened, and the surrounding Donchian family is strongly dependent on rare winners. It is also a non-ML baseline and therefore cannot be the final project system.

## Second place with complete metrics

The Donchian after-loser path `a70626d9e484285f2cb4|after_loser` is provisional rank 2 and supplies the nearest complete risk record for the same specification.

- 12-bps geometric daily growth: `0.0829996%`
- 24-bps geometric daily growth: `0.0631845%`
- 12/24-bps total return: `+35.3674% / +25.9293%`
- 12/24-bps PF: `1.8083 / 1.6226`
- MDD: approximately `11.03%`
- trades: `89`
- median account return: `-50.00 bps`
- top-five positive-PnL share: `68.49%` at 12 bps
- top-10%-winner-removed return: `-25.7775%` at 12 bps and `-26.3062%` at 24 bps

## Lower provisional ranks

1. Donchian all-breakout comparator — `0.0900854%` daily at 12 bps; complete risk ledger missing.
2. Donchian after-loser — `0.0829996%` daily at 12 bps; complete metrics but severe winner dependence.
3. aligned continuation `33034b092ffd271a` — `0.0227977%` daily under its recorded base-cost contract; legacy exit-contract re-audit pending.
4. perp overshoot reversal `191444bb0a4348e2a52b` — `0.0118976%` daily; legacy exit-contract re-audit pending.
5. liquidation exhaustion reversal `0c0b773a5be4eab4` — `0.00358316%` daily, very sparse.
6. DVOL low-VRP residual continuation — `0.0034002%` daily; legacy exit-contract re-audit pending.
7. high-resistance sweep `c232ae43b7a1401d` — `0.0024555%` daily.
8. fragmented-flow reversal `95f3b144d5a291abc61c` — `0.0020533%` daily, four trades.

Economic-gate failure and ranking are separate, but a strategy that violates the fixed exit contract cannot rank. A higher incomplete path is not suppressed merely because a lower path has a fuller report.

Rank does not determine research priority.

## Work stopped

The fixed 2024 portfolio takeover that combined the ineligible dynamic state-exit with aligned continuation remains stopped before any 2024 strategy outcome is opened.

## Current objective

Do not protect the new first place. It is only the highest recorded current-contract benchmark and is still roughly `11.10x` short of 1% daily growth at its 12-bps proxy cost. It lacks Bybit execution, funding, complete risk fields, sequential OOS and ML.

Continue only retained high-information ML paths with strategy-defined exits:

- Coinbase aggressive spot flow into delayed executable Bybit BBO;
- Bybit mark/index acceptance after an executable liquidity raid;
- funding-boundary movement-hazard OCO if its frozen source passes.

A positive hard-valid result is inserted immediately. A negative result is retired without model, feature, threshold, stop, risk or leverage rescue.

## Current blockers

No candidate has robust sequential OOS evidence after realistic Bybit execution, funding, concentration removal and regime changes. The current benchmark has missing risk fields and no Bybit replay; the fully measured second place has a negative median and collapses after winner removal. The project still lacks a high-frequency, cost-sized ML information unit with repeatable positive median expectancy.

## Next exact action

Consume the already-running Coinbase and mark/index ML workflows as soon as they become decision-ready. If neither survives 24-bps costs and winner removal, switch to a materially new forced-flow or inventory-transfer information source rather than extending the Donchian or legacy completed-bar grids.
