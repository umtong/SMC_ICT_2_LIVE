# Current state

- revision: 13
- phase: ACTIVE_RESEARCH
- current first place: `FIRST-20260726-DONCHIAN-ALL-A70626D9E484`
- first-place stage: `PRELIMINARY_CAUSAL_BINANCE_PROXY`
- target_status: `NOT_MET`
- live_order_permission: none
- repository: `umtong/SMC_ICT_2_LIVE`

## Ranking correction

The former first place, dynamic state-exit `021fbab613517a31ad98` from `RES-20260725-DYNAMIC-FACTOR-001`, is removed from the current-contract ranking.

Its SHA-verified implementation precommits `maximum_hold_bars=96`, initializes surviving positions to close at the timeout open exactly 480 minutes after entry, and only replaces that default when an ATR stop or state condition fires. That is an elapsed-time liquidation and conflicts with the fixed project rule that exits must arise from strategy logic. The historical result remains in the Result Registry but is not active-ranking eligible.

## Current first place

The provisional first place is the Donchian all-breakout comparator for specification `a70626d9e484285f2cb4` from `RES-20260726-DONCHIAN-DEPENDENCE-001` / PR #61.

- rule: completed 60-minute Donchian channel, entry lookback 96 and exit channel 48
- 12-bps geometric daily growth: `0.0900854%`
- 24-bps geometric daily growth: `0.0700189%`
- 1% target gap at 12 bps: `0.9099146 percentage points per UTC calendar day`
- target fraction at 12 bps: `9.00854%`
- required growth multiple at 12 bps: approximately `11.10x`
- elapsed-time liquidation: none
- operational exits: ATR stop or completed Donchian channel exit

The compact result did not preserve this comparator's full trade ledger, maximum drawdown, profit factor or concentration fields. Those values remain unknown and are not inferred from the after-loser route. The candidate therefore has `VERY_LOW` comparison confidence.

It is first because it has the highest recorded after-cost geometric daily growth among paths whose exit implementation has been audited against the current contract. Its 24-bps growth is also above the former first place's 12-bps actual-funding growth.

This candidate is not a final solution. It is a Binance USD-M proxy, historical funding and exact Bybit execution are absent, no 2024 or later sequential interval was opened, the broader Donchian family is strongly dependent on rare winners, and the route is non-ML. Rank records the best current quantitative result; it does not protect the route or satisfy the mandatory ML system requirement.

## Second place with complete metrics

The same specification's after-loser route is provisional rank 2 and supplies the nearest complete risk record:

- 12-bps geometric daily growth: `0.0829996%`
- 24-bps geometric daily growth: `0.0631845%`
- total return: `+35.3674% / +25.9293%` at 12/24 bps
- maximum drawdown: `11.0226% / 11.0298%`
- trades: `89`
- profit factor: `1.8083 / 1.6226`
- median account return: `-50.00 bps`
- top-five positive-PnL share: `68.49% / 67.35%`
- top-10%-winner-removed return: `-25.7775% / -26.3062%`

The all-breakout comparator outperformed this conditional after-loser route, so no special after-loser dependency is established.

## Lower provisional ranks

1. Donchian all-breakout comparator `a70626d9e484285f2cb4|all` — `0.0900854%` daily at 12 bps, `0.0700189%` at 24 bps; risk fields incomplete.
2. Donchian after-loser `a70626d9e484285f2cb4|after_loser` — `0.0829996%` daily at 12 bps, `0.0631845%` at 24 bps; severe winner concentration.
3. aligned continuation `33034b092ffd271a` — `0.0227977%` daily under its recorded base-cost contract; legacy exit-contract re-audit pending.
4. perp overshoot reversal `191444bb0a4348e2a52b` — `0.0118976%` daily; legacy exit-contract re-audit pending.
5. liquidation exhaustion reversal `0c0b773a5be4eab4` — `0.00358316%` daily, very sparse.
6. DVOL low-VRP residual continuation — `0.0034002%` daily; legacy exit-contract re-audit pending.
7. high-resistance sweep `c232ae43b7a1401d` — `0.0024555%` daily.
8. fragmented-flow reversal `95f3b144d5a291abc61c` — `0.0020533%` daily, four trades.

Economic-gate failure and ranking are separate, but a strategy that violates the fixed exit contract is not ranking-eligible.

## Work stopped

The fixed 2024 portfolio takeover that combined the now-ineligible dynamic state-exit with aligned continuation is closed before any 2024 strategy outcome is opened. Replaying an invalid component would consume research budget without producing a ranking-eligible portfolio.

## Current objective

Do not protect or polish the new first place. It remains a provisional benchmark and is still approximately 11.10 times short of the 1% daily-growth objective at its recorded 12-bps path.

Continue only high-information ML paths with strategy-defined exits:

- Coinbase aggressive spot flow into delayed executable Bybit BBO;
- Bybit mark/index acceptance after an executable liquidity raid;
- funding-boundary movement-hazard OCO if its frozen source passes.

A positive hard-valid result is inserted immediately. A negative result is retired without model, feature, threshold, stop, risk or leverage rescue.

## Current blockers

No candidate has robust sequential OOS evidence after realistic Bybit execution, funding, concentration removal and regime changes. The provisional first place lacks complete risk fields and Bybit replay and is non-ML. The project still lacks a high-frequency, cost-sized ML information unit with repeatable positive median expectancy.

## Next exact action

Consume the already-running Coinbase and mark/index ML workflows as soon as they become decision-ready. If neither survives 24-bps costs and winner removal, switch to a materially new forced-flow or inventory-transfer information source rather than extending the Donchian or legacy completed-bar grids.
