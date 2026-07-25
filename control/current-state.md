# Current state

- revision: 8
- phase: ACTIVE_RESEARCH
- current first place: `FIRST-20260725-ALIGNED-CONTINUATION-33034B092FFD271A`
- first-place stage: `EXPLORATORY`
- target_status: `NOT_MET`
- live_order_permission: none
- repository: `umtong/SMC_ICT_2_LIVE`
- Drive root: resolved privately through `config/project.local.toml` or `00_PROJECT_BINDING`

## Current strategy ranking

The proposed current first place is the `aligned_continuation` specification `33034b092ffd271a` from `RES-20260725-ABS-FLOW-001` / PR #35.

- approximately 15 bps round-trip geometric daily growth: `0.0227977%`
- 1% target gap: `0.9772023 percentage points per trading day`
- target fraction: `2.27977%`
- total return: `+15.6276%`
- maximum drawdown: `6.4718%`
- trades: `184`
- profit factor: `1.3065`
- top-five positive-trade share: `18.00%`
- return after removing the top five trades: `+3.6352%`
- approximately 30 bps round-trip return: `+7.8715%`
- approximately 30 bps geometric daily growth: `0.0118956%`

It is first because it has the smallest verified after-cost geometric daily-growth gap among ranked hard-valid strategy results under the current evidence. The rank is provisional and comparison confidence is low because windows, symbols and exact cost contracts are not fully normalized. The preregistered yearly robustness gate failed, so no sequential 2024 or 2025H1 interval was opened.

The current execution-routing component first place is `RES-20260725-1510-L1-EXEC-001`, which improved modeled execution drag but has negative standalone expectancy.

## Pending closer candidate

PR #25 candidate `021fbab613517a31ad98` reports `0.0571%` after-cost geometric daily growth, positive returns at 12/18/24 bps, 194 trades, PF `1.502` and MDD `4.63%`. Its observed gap to the 1% target is smaller than the proposed first place and it would become provisional first if hard-valid evidence completes.

It remains outside the ranking because workflow run `30157741432` failed during immutable extension-bundle reconstruction. Compilation, causal self-tests and safety/stage-seal checks were skipped. Known weaknesses include `-21.93%` after removing the top 10% trades, losses in all four frozen 2024 portfolios, and absent funding/order-book execution.

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
- dynamic common-factor residual verification;
- conditional reconciliation of the folder/action lifecycle change.

Reported work has rejected the ordinary five-minute and prior-volume dollar-clock absorption-family screens, causal alpha wave 1, exact funding-settlement families, completed-bar cross-asset lead-lag, fixed BTC OI-shock families, transcript-derived five-minute formulations, and liquidity-sweep engulfing first-touch variants under their tested dependencies. These negative results remain reusable evidence.

## Current objective

Continue the highest-value unresolved strategy, execution and account-path research. Choose work independently of current rank. When a result becomes decision-ready, rank it by closeness to the full objective and update the table.

## Current blockers

The proposed first place remains far below target, failed the preregistered yearly robustness gate, becomes negative after removing its top five winners at approximately 30 bps, has no opened sequential OOS interval, and has slow median slot occupation of roughly 588 to 683 minutes. The economically closer PR #25 candidate cannot enter the ranking until its failed reproducibility workflow is repaired. No candidate has survived sequential OOS with robust cost, concentration and capital-velocity behavior.

## Next exact action

Repair and rerun PR #25 immutable-bundle verification while materially advancing the active spot-perp and flow-size-impact claims. Move new alpha discovery away from ordinary absorption thresholds and activity-clock variants unless a materially different state variable or execution mechanism is introduced.
