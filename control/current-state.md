# Current state

- revision: 8
- phase: ACTIVE_RESEARCH
- current first place: `FIRST-20260725-DYNAMIC-FACTOR-021FBAB613517A31`
- first-place stage: `EXPLORATORY`
- target_status: `NOT_MET`
- live_order_permission: none
- repository: `umtong/SMC_ICT_2_LIVE`
- Drive root: resolved privately through `config/project.local.toml` or `00_PROJECT_BINDING`

## Current strategy ranking

The proposed current first place is the `dynamic_factor_state_exit` specification `021fbab613517a31ad98` from `RES-20260725-DYNAMIC-FACTOR-001` / PR #25.

- 12 bps geometric daily growth: `0.0573077%`
- 1% target gap: `0.9426923 percentage points per trading day`
- target fraction: `5.73077%`
- total return: `+23.2585%`
- maximum drawdown: `4.6174%`
- trades: `194`
- profit factor: `1.5041`
- top-five positive-trade share: `35.35%`
- return at 18 bps: `+16.7170%`
- return at 24 bps: `+11.2649%`
- return after removing the largest 10% trades: `-21.8583%`
- frozen following-year portfolios positive: `0 of 4`

It is first because it has the smallest verified after-cost geometric daily-growth gap among ranked hard-valid strategy results and remains positive at all three modeled cost profiles after exact official funding cashflows. The rank is provisional and comparison confidence is low because windows and execution contracts are not fully normalized. The preregistered economic gate failed and the result is not deployable.

The second-ranked result is `aligned_continuation 33034b092ffd271a` from `RES-20260725-ABS-FLOW-001` / PR #35: approximately 15 bps geometric daily growth `0.0227977%`, approximately 30 bps growth `0.0118956%`, 184/183 trades, PF `1.3065/1.1597`, MDD `6.4718%/7.8395%`, and top-five positive-trade share `18.00%/19.74%`. It also failed its preregistered yearly robustness gate and opened no sequential OOS.

The current execution-routing component first place is `RES-20260725-1510-L1-EXEC-001`, which improved modeled execution drag but has negative standalone expectancy.

## Ranking policy

- Hard-invalid results are excluded from strategy ranking but remain in the failure record.
- The primary ranking criterion is closeness to the full project objective, led by the gap to 1% after-cost geometric daily growth.
- A forced-liquidation or irrecoverable account path cannot outrank a survival-qualified candidate solely through raw return.
- Drawdown/recovery, liquidation/tail risk, concentration, effective independent trades, execution robustness, capital efficiency and comparison confidence resolve similar or uncertain target gaps.
- Rank does not determine research priority, validation budget, protection, or the next work item.
- Results are recorded once; rank changes update the ranking record without repeated backup or validation.

## Active work

Material active claims currently cover:

- spot/perpetual leadership and price discovery;
- flow-size and price-impact efficiency states;
- multi-level L2 passive fill and conditional post-fill toxicity;
- cross-venue forward capture and private-execution evidence;
- conditional reconciliation of the folder/action lifecycle change.

Reported work has rejected the ordinary five-minute and prior-volume dollar-clock absorption-family screens, dynamic common-factor residual families at their registered economic gate, cross-sectional funding crowding, causal alpha wave 1, exact funding-settlement families, completed-bar cross-asset lead-lag, fixed BTC OI-shock families, transcript-derived five-minute formulations, and liquidity-sweep engulfing first-touch variants under their tested dependencies. These negative results remain reusable evidence.

## Current objective

Continue the highest-value unresolved strategy, execution and account-path research. Choose work independently of current rank. When a result becomes decision-ready, rank it by closeness to the full objective and update the table.

## Current blockers

The first place remains far below target, depends materially on its largest trades, has negative median trade expectancy, and all four portfolios frozen from development lost in the following year. The second place has no opened sequential OOS, fails its yearly robustness and high-cost top-five-removal gates, and occupies the single slot for roughly 588 to 683 minutes. No candidate has survived sequential OOS with robust cost, concentration, execution and capital-velocity behavior.

## Next exact action

Materially advance the active spot-perp, flow-size-impact, L2 maker-toxicity and cross-venue forward claims. New alpha discovery should introduce a genuinely different state variable or execution mechanism rather than repeat ordinary absorption thresholds, activity clocks or completed-bar factor tuning.
