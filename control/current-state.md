# Current state

- revision: 14
- phase: ACTIVE_RESEARCH
- current first place: `FIRST-20260726-DONCHIAN-ALLBREAKOUT-A70626D9`
- first-place stage: `PRELIMINARY_CAUSAL_BINANCE_PROXY`
- target_status: `NOT_MET`
- live_order_permission: none
- repository: `umtong/SMC_ICT_2_LIVE`

## Ranking correction

The provisional first place is now the matched all-breakout comparator for Donchian specification `a70626d9e484285f2cb4` inside `RES-20260726-DONCHIAN-DEPENDENCE-001` / PR #61.

- rule: completed 60-minute Donchian channel, entry lookback 96, exit channel 48, failsafe entry channel 240, all qualifying breakouts
- 24-bps geometric daily growth: `0.0700189%`
- 12-bps geometric daily growth: `0.0900854%`
- 1% target gap at 24 bps: `0.9299811 percentage points per UTC calendar day`
- target fraction at 24 bps: `7.00189%`
- target multiple still required: `14.28186x`

It replaces the after-loser path because both paths use the same current-contract-compatible channel and stop logic, while the all-breakout comparator has higher recorded growth under the same 24-bp proxy contract.

The comparison confidence is `VERY_LOW`. The source is Binance USD-M completed bars, historical funding and exact Bybit execution were not replayed, no 2024 or later interval was opened, and the durable record did not persist the comparator's complete trade ledger, drawdown or concentration fields. Rank is not economic-gate passage or deployment approval.

## Current cumulative ranking

1. Donchian matched all-breakout `a70626d9e484285f2cb4` — `0.0700189%` daily at 24 bps.
2. Donchian after-loser `a70626d9e484285f2cb4` — `0.0631845%` daily at 24 bps.
3. aligned continuation `33034b092ffd271a` — `0.0227977%` daily under its recorded base-cost contract.
4. perp overshoot reversal `191444bb0a4348e2a52b` — `0.0118976%` daily.
5. liquidation exhaustion reversal `0c0b773a5be4eab4` — `0.00358316%` daily.
6. DVOL low-VRP residual continuation — `0.0034002%` daily.
7. high-resistance sweep `c232ae43b7a1401d` — `0.0024555%` daily.
8. fragmented-flow reversal `95f3b144d5a291abc61c` — `0.0020533%` daily.

The former dynamic state-exit remains unranked because its immutable `hold_bars` terminal exit is a prohibited elapsed-time liquidation. The stale PR #173 is not authoritative because it reintroduced that path.

## Current objective

Do not protect or extend the Donchian benchmark. At 24 bps it remains approximately `14.28` times short of the 1% daily-growth objective and lacks complete risk evidence.

The profit-first research path is one small set of distinct ML information units:

- four-asset direct after-cost utility regression with stateful KEEP/SWITCH/FLAT decisions;
- Coinbase aggressive spot flow into delayed executable Bybit BBO;
- forced-flow transfer from Aave liquidation events;
- materially new inventory-transfer or forced-flow information if those fail.

A positive hard-valid result is inserted immediately. A negative information unit is retired without threshold, stop, risk, leverage or feature-grid rescue.

## Current blockers

No candidate has robust sequential OOS evidence after realistic Bybit execution, funding, winner removal and regime changes. The current first place is a 2023-only proxy with incomplete trade-risk fields. The project still lacks a cost-sized ML information unit with repeatable positive median expectancy.

Rank does not determine research priority.

## Next exact action

Restore the common validation harness, then complete the already-implemented direct-utility ML screen. Its first failure was data continuity handling rather than an alpha result. Treat source gaps causally, preserve 2024-2026 sealing, and consume its untouched confirmation output. In parallel, consume the Coinbase and Aave forced-flow outputs when decision-ready. If these paths fail, switch information source rather than extending completed-bar Donchian grids.
