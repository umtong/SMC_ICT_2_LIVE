# Current state

- revision: 14
- phase: ACTIVE_RESEARCH
- current first place: `FIRST-20260726-DONCHIAN-ALL-A70626D9`
- first-place stage: `PRELIMINARY_CAUSAL_BINANCE_PROXY`
- target_status: `NOT_MET`
- live_order_permission: none
- repository: `umtong/SMC_ICT_2_LIVE`

## Ranking correction

The former first place, dynamic state-exit `021fbab613517a31ad98`, is removed from the active ranking because its immutable engine exits surviving trades after a fixed `hold_bars` horizon. That elapsed-time liquidation violates the current project contract.

Revision 13 initially placed the fully recorded Donchian after-loser path first while its higher-growth matched all-breakout comparator lacked expanded metrics in the compact result. Revision 14 independently reproduced the comparator from the exact registered snapshot and source, so incomplete evidence no longer justifies suppressing it.

## Current first place

The provisional first place is Donchian all-breakout `a70626d9e484285f2cb4|all`.

- rule: completed 60-minute Donchian channel, entry lookback 96, exit channel 48, all breakouts
- 12-bps geometric daily growth: `0.0900854%`
- 18-bps geometric daily growth: `0.0794137%`
- 24-bps geometric daily growth: `0.0700189%`
- 1% target gap at 24 bps: `0.9299811 percentage points per UTC calendar day`
- total return at 24 bps: `+29.1080%`
- maximum drawdown at 24 bps: `9.8554%`
- trades: `99`
- profit factor at 24 bps: `1.6274`
- median account return: `-50.00 bps`
- win rate: `20.20%`
- top-five positive-PnL share: `64.22%`
- top-10%-winner-removed return: `-26.9469%`
- first-half / second-half return: `+21.6612% / +6.1209%`

The comparison confidence is `VERY_LOW`: Binance proxy, funding omitted, no exact Bybit replay, no 2024+, and severe positive-tail dependence. It is also non-ML, so it is only the current performance benchmark, not a final-system candidate.

## Current provisional ranks

1. Donchian all-breakout — `0.0700189%` daily at 24 bps.
2. Donchian after-loser — `0.0631845%` daily at 24 bps.
3. aligned continuation — `0.0227977%` daily; legacy exit audit pending.
4. perp overshoot reversal — `0.0118976%` daily; legacy exit audit pending.
5. liquidation exhaustion reversal — `0.00358316%` daily, very sparse.
6. DVOL low-VRP residual continuation — `0.0034002%` daily; legacy exit audit pending.
7. high-resistance sweep — `0.0024555%` daily.
8. fragmented-flow reversal — `0.0020533%` daily, four trades.

## Current objective

Rank does not determine research priority.

Do not protect the new first place. It remains roughly `14.28` times short of the 1% daily-growth objective and fails concentration, exact-Bybit, funding, sequential-OOS and ML requirements.

Consume the already-running high-information ML paths with strategy-defined exits:

- Coinbase aggressive spot flow into delayed executable Bybit BBO;
- Bybit mark/index acceptance after an executable liquidity raid;
- funding-boundary movement-hazard OCO;
- external forced-flow paths only when source gates pass.

A positive hard-valid result is inserted immediately. A negative result is retired without model, feature, threshold, stop, risk or leverage rescue.

## Next exact action

Finish Coinbase and mark/index ML. In parallel, complete exact-arrival V5D. Any candidate exceeding `0.0700189%` daily after comparable realistic cost and current-contract exits takes first place immediately.
