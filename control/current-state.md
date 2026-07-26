# Current state

- revision: 13
- phase: ACTIVE_RESEARCH
- current first place: `FIRST-20260726-DONCHIAN-AFTER-LOSER-A70626D9`
- first-place stage: `PRELIMINARY_CAUSAL_BINANCE_PROXY`
- target_status: `NOT_MET`
- live_order_permission: none
- repository: `umtong/SMC_ICT_2_LIVE`

## Ranking correction

The former first place, dynamic state-exit `021fbab613517a31ad98` from `RES-20260725-DYNAMIC-FACTOR-001`, is removed from the current-contract ranking.

Its immutable implementation stores `hold_bars`, computes the terminal index as `entry + hold`, and exits any surviving trade at that fixed future bar. That is an elapsed-time liquidation and conflicts with the fixed project rule that exits must arise from strategy logic rather than a maximum holding period. The historical result remains in the Result Registry but is not a valid current first place.

## Current first place

The provisional first place is Donchian after-loser `a70626d9e484285f2cb4` from `RES-20260726-DONCHIAN-DEPENDENCE-001` / PR #61.

- rule: completed 60-minute Donchian channel, entry lookback 96, exit channel 48, failsafe entry channel 240, after-loser mode
- 24-bps geometric daily growth: `0.0631845%`
- 1% target gap: `0.9368155 percentage points per UTC calendar day`
- target fraction: `6.31845%`
- total return: `+25.9293%`
- maximum drawdown: `11.0298%`
- trades: `89`
- profit factor: `1.6226`
- median account return: `-50.00 bps`
- win rate: `17.98%`
- top-five positive-PnL share: `67.35%`
- top-10%-winner-removed return: `-26.3062%`
- first-half / second-half return: `+20.0763% / +4.8744%`

It is first only because its fully recorded 24-bps daily growth exceeds the former first place's 12-bps daily growth while using channel and stop exit logic rather than elapsed-time liquidation.

The comparison confidence is `VERY_LOW`. The source is a Binance USD-M proxy, historical funding and Bybit execution were not replayed, no 2024 or later interval was opened, and the result is dominated by rare large winners. The matched all-breakout comparator recorded still higher 24-bps growth, so the after-loser dependency itself is not established.

## Lower provisional ranks

1. Donchian after-loser `a70626d9e484285f2cb4` — `0.0631845%` daily at 24 bps.
2. aligned continuation `33034b092ffd271a` — `0.0227977%` daily under its recorded base-cost contract; legacy exit-contract re-audit pending.
3. perp overshoot reversal `191444bb0a4348e2a52b` — `0.0118976%` daily; legacy exit-contract re-audit pending.
4. liquidation exhaustion reversal `0c0b773a5be4eab4` — `0.00358316%` daily, very sparse.
5. DVOL low-VRP residual continuation — `0.0034002%` daily; legacy exit-contract re-audit pending.
6. high-resistance sweep `c232ae43b7a1401d` — `0.0024555%` daily.
7. fragmented-flow reversal `95f3b144d5a291abc61c` — `0.0020533%` daily, four trades.

Economic-gate failure and ranking are separate, but a strategy that violates the fixed exit contract is not ranking-eligible.

## Work stopped

The fixed 2024 portfolio takeover that combined the now-ineligible dynamic state-exit with aligned continuation is stopped before any 2024 strategy outcome is opened. Replaying an invalid component would consume research budget without producing a ranking-eligible portfolio.

## Current objective

Rank does not determine research priority.

Do not protect the new first place. It remains only a provisional benchmark and is still roughly 15.83 times short of the 1% daily-growth objective.

Continue the retained high-information ML paths that have strategy-defined exits:

- Coinbase aggressive spot flow into delayed executable Bybit BBO;
- Bybit mark/index acceptance after an executable liquidity raid;
- funding-boundary movement-hazard OCO if its frozen source passes.

A positive hard-valid result is inserted immediately. A negative result is retired without model, feature, threshold, stop, risk or leverage rescue.

## Current blockers

No candidate has robust sequential OOS evidence after realistic Bybit execution, funding, concentration removal and regime changes. The provisional first place has severe positive-tail dependence and no Bybit replay. The project still lacks a high-frequency, cost-sized ML information unit with repeatable positive median expectancy.

## Next exact action

Consume the already-running Coinbase and mark/index ML workflows as soon as they become decision-ready. If neither survives 24-bps costs and winner removal, switch to a materially new forced-flow or inventory-transfer information source rather than extending the Donchian or legacy completed-bar grids.
