# Current state

- revision: 11
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
- approximately 30 bps geometric daily growth: `0.0118956%`

It is hard-valid but failed the preregistered yearly robustness gate. No sequential 2024 or 2025H1 interval was opened, and the approximately 30 bps path becomes negative after removing the top five winners.

The provisional third place is `perp_overshoot_reversal 191444bb0a4348e2a52b` from `RES-20260726-SPOT-PERP-LEADERSHIP-001` / PR #43.

- 12 bps geometric daily growth: `0.0118976%`
- target gap: `0.9881024 percentage points per trading day`
- total return: `+4.4380%`
- maximum drawdown: `1.2337%`
- trades: `17`
- profit factor: `2.4637`
- top-five positive-trade share: `92.76%`
- top-10%-removed return: `-0.5817%`
- 18/24 bps geometric daily growth: `0.0094770%` / `0.0070550%`

It is hard-valid but failed five development gates, including sample count, positive median trade and top-trade-removal robustness. Zero of 496 candidates survived; later stages remained unopened. Its rank reflects target proximity only, with low comparison confidence.

The provisional fourth place is the raw DVOL-conditioned residual candidate `1b4ec83c59bb98660c23` from `RES-20260726-DVOL-XSEC-001`.

- 12 bps geometric daily growth: `0.0034002%`
- target gap: `0.9965998 percentage points per trading day`
- total return: `+0.9291%`
- maximum drawdown: `3.4484%`
- trades: `76`
- profit factor: `1.0684`
- top-10%-removed return: `-7.3742%`

It lost at 18 and 24 bps, had a negative median trade and produced zero development survivors. The former `high_resistance_sweep c232ae43b7a1401d` remains rank 5.

The provisional sixth place is `fragmented_flow_reversal 95f3b144d5a291abc61c` from `RES-20260726-FLOW-IMPACT-EFFICIENCY-001` / PR #52.

- 12 bps geometric daily growth: `0.0020533%`
- target gap: `0.9979467 percentage points per trading day`
- total return: `+0.7523%`
- maximum drawdown: `0.3551%`
- trades: `4`
- profit factor: `2.1284`
- top-five positive-trade share: `100%`
- top-10%-removed return: `-0.0751%`
- 18/24 bps total return: `+0.5491%` / `+0.3461%`

It is hard-valid but failed the sample, concentration, top-trade-removal and half-year gates. Zero of 864 candidates survived, every candidate with at least 200 trades had negative after-cost growth, and later stages remained unopened. Comparison confidence is very low and the family is not deployable.

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

Material active claims include the fixed raw-event two-strategy portfolio, L2 maker toxicity, exact-arrival cross-venue V5D, multi-asset positioning states, COIN-M/cross-margin collateral stress and option-surface skew/term structure. The flow-size/impact-efficiency claim is now reported and should not receive adjacent-threshold tuning under the recorded dependency fingerprint.

Reported work has rejected causal alpha wave 1, exact funding-settlement families, completed-bar fixed lead-lag, fixed BTC OI-shock families, transcript-derived five-minute formulations, liquidity-sweep engulfing first-touch variants, ordinary five-minute absorption, prior-volume dollar-clock absorption, completed-bar spot/perpetual price-discovery thresholds, DVOL-conditioned residual routing and ordinary one-minute activity/impact threshold routing under their tested dependencies.

## Current objective

Finish and reuse decision-ready outputs from active claims, especially the fixed account-level portfolio and corrected sub-minute cross-venue replay. If none materially closes the target gap, change the payoff structure rather than retuning reported directional thresholds. A high-information next direction is movement-hazard-conditioned two-sided OCO execution, provided active cross-venue and L2 scopes do not already cover it.

## Current blockers

Every positive raw rank remains far below the 1% target and has material concentration, sample, cost or sequential-robustness defects. No candidate has survived sequential selection with robust cost, concentration and regime behavior. Capital velocity remains low, and exact historical queue/depth execution is incomplete.

## Next exact action

Consume decision-ready fixed-portfolio, cross-venue V5D, L2 maker, positioning, COIN-M/cross-margin and option-surface outputs as they finish. Do not retune dynamic-factor, ordinary absorption, DVOL, completed-bar spot/perpetual or one-minute flow-impact dependencies. If active outputs remain below target, search claims and open a non-overlapping movement-hazard-conditioned two-sided OCO or other structurally different sub-minute payoff study.
