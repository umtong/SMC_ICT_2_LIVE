# Current state

- revision: 9
- phase: ACTIVE_RESEARCH
- current first place: `FIRST-20260725-DYNAMIC-STATE-021FBAB6`
- first-place stage: `EXPLORATORY`
- target_status: `NOT_MET`
- live_order_permission: none
- repository: `umtong/SMC_ICT_2_LIVE`
- Drive root: resolved privately through `config/project.local.toml` or `00_PROJECT_BINDING`

## Current strategy ranking

The current first place is dynamic state-exit candidate `021fbab613517a31ad98` from `RES-20260725-DYNAMIC-FACTOR-001` / PR #25.

- 12 bps and actual-funding geometric daily growth: `0.0573077%`
- 1% target gap: `0.9426923 percentage points per trading day`
- target fraction: `5.73077%`
- total return: `+23.2585%`
- maximum drawdown: `4.6174%`
- trades: `194`
- profit factor: `1.5041`
- top-five positive-trade share: `35.35%`
- return at 18 bps: `+16.7170%`
- return at 24 bps: `+11.2649%`

It remains first because it has the smallest verified recorded after-cost daily-growth gap among hard-valid results. The rank is provisional: the registered economic gate failed, top-10%-removed return is `-21.8583%`, median per-trade return is negative, all four portfolios frozen from 2023 lost in 2024, and the exact candidate has no opened 2024 out-of-sample interval.

The current second place is `aligned_continuation 33034b092ffd271a` from `RES-20260725-ABS-FLOW-001` / PR #35.

- approximately 15 bps round-trip geometric daily growth: `0.0227977%`
- target gap: `0.9772023 percentage points per trading day`
- total return: `+15.6276%`
- maximum drawdown: `6.4718%`
- trades: `184`
- profit factor: `1.3065`
- top-five positive-trade share: `18.00%`
- approximately 30 bps total return: `+7.8715%`
- approximately 30 bps geometric daily growth: `0.0118956%`

It is hard-valid but failed the preregistered yearly robustness gate. No sequential 2024 or 2025H1 interval was opened, and the approximately 30 bps path becomes negative after removing the top five winners. The former `high_resistance_sweep c232ae43b7a1401d` is rank 3.

The current execution-routing component first place remains `RES-20260725-1510-L1-EXEC-001`, which improved modeled execution drag but has negative standalone expectancy.

## Ranking policy

- Hard-invalid results are excluded from strategy ranking but remain in the failure record.
- The primary ranking criterion is closeness to the full project objective, led by the gap to 1% after-cost geometric daily growth.
- A forced-liquidation or irrecoverable account path cannot outrank a survival-qualified candidate solely through raw return.
- Drawdown/recovery, liquidation/tail risk, concentration, effective independent trades, execution robustness, capital efficiency and comparison confidence resolve similar or uncertain target gaps.
- Economic gate failure, validation stage and deployability are reported separately from rank.
- Rank does not determine research priority, validation budget, protection or the next work item.
- Results are recorded once; rank changes update the ranking record without repeated backup or validation.

## Active work

Material active claims include spot/perpetual price discovery, flow-size/impact-efficiency state research, L2 maker toxicity, cross-venue forward capture and multi-asset positioning states. Dynamic-factor and ordinary absorption/activity-clock families are reported and should not receive adjacent-threshold tuning.

Reported work has rejected causal alpha wave 1, exact funding-settlement families, completed-bar fixed lead-lag, fixed BTC OI-shock families, transcript-derived five-minute formulations, liquidity-sweep engulfing first-touch variants, ordinary five-minute absorption and prior-volume dollar-clock absorption under their tested dependencies.

## Current objective

Finish and reuse decision-ready outputs from active claims. If none materially closes the target gap, open a non-overlapping information-source claim rather than retuning reported families. Highest-value unclaimed directions are official COIN-M versus USD-M collateral-stress transmission and sub-minute cross-exchange price discovery/liquidation replenishment.

## Current blockers

The first two ranks remain far below the 1% target and both depend on upper-tail trades. Neither has robust sequential OOS evidence. Capital velocity remains low, and historical queue/depth execution is incomplete. No candidate has survived sequential selection with robust cost, concentration and regime behavior.

## Next exact action

Reconcile and consume active spot-perp, flow-size, L2 maker, cross-venue and positioning results. Do not retune dynamic-factor or ordinary absorption dependencies. Claim the highest-value non-overlapping information source only after those active scopes are checked.
