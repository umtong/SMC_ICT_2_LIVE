# Current state

- revision: 8
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

It is first because it has the smallest verified recorded after-cost daily-growth gap among hard-valid strategy results and is materially stronger than the prior first place in higher-cost performance, trade count, profit factor, drawdown and top-five concentration.

The ranking remains provisional with low-to-moderate comparison confidence. The candidate failed the preregistered economic gate: top-10%-removed return is `-21.8583%`, median per-trade return is negative, all four portfolios frozen from 2023 lost in 2024, and the exact candidate has no opened 2024 out-of-sample interval. Historical order-book queue replay is absent.

The prior `high_resistance_sweep c232ae43b7a1401d` is now rank 2.

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

Material active claims include spot/perpetual price discovery and flow-size/impact-efficiency state research. The dynamic-factor dependency family is now reported and should not receive adjacent-threshold tuning.

Reported work has rejected causal alpha wave 1, exact funding-settlement families, completed-bar fixed lead-lag, fixed BTC OI-shock families, transcript-derived five-minute formulations, liquidity-sweep engulfing first-touch variants and the current dynamic-factor family for practical promotion under their tested dependencies. These negative results remain reusable evidence.

## Current objective

Continue the highest-value unresolved strategy, execution and account-path research independently of rank. Reuse active spot-perp and flow-size outputs. If they do not produce a decision-ready challenger, move to a non-overlapping information source such as COIN-M collateral-stress transmission or sub-minute cross-exchange price discovery.

## Current blockers

The first place remains far below the 1% target, depends on upper-tail trades, is concentrated in SOL/XRP and lacks exact-candidate sequential out-of-sample evidence and historical queue execution. No candidate has survived sequential selection with robust cost, concentration and regime behavior.

## Next exact action

Finish and register active spot-perp and flow-size-impact claims. Do not retune the dynamic-factor dependency family. Search active claims before opening the next non-overlapping Work Claim; prefer official COIN-M versus USD-M collateral-stress transmission or sub-minute cross-exchange price discovery if those scopes remain unclaimed.
