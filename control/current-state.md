# Current state

- revision: 12
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

The newly reconciled provisional fourth place is `exhaustion_reversal 0c0b773a5be4eab4` from `RES-20260726-LIQUIDATION-REFILL-001` / PR #58.

- 18 bps development full-calendar geometric daily growth: `0.00358316%`
- target gap: `0.99641684 percentage points per trading day`
- development total return: `+1.31642%`
- development maximum drawdown: `1.4925%`
- development trades: `19`
- development profit factor: `1.32394`
- development median trade return: `+0.3092%`
- 24 bps development total return: `+0.24768%`

This candidate is inserted because hard validity and the normalized positive account-growth metric satisfy provisional ranking eligibility even though the economic gate failed. Comparison confidence is very low: the same rule lost `7.35461%` in the 2021–2022 fit period, the 18-bps top-10%-winner-removal return was `-0.00784%`, only eight development sample days were active, and validation plus 2024–2026 remained unopened.

The former fourth through eighth places shift down one rank:

- rank 5: `LOW_VRP_RESIDUAL_CONTINUATION 1b4ec83c59bb98660c23` from `RES-20260726-DVOL-XSEC-001`, `0.0034002%` daily growth;
- rank 6: `high_resistance_sweep c232ae43b7a1401d` from `RES-20260725-ALPHA-HYP-001`, `0.0024555%` daily growth;
- rank 7: `fragmented_flow_reversal 95f3b144d5a291abc61c` from `RES-20260726-FLOW-IMPACT-EFFICIENCY-001`, `0.0020533%` daily growth;
- ranks 8 and 9 remain the negative `balance_to_imbalance` and cross-asset lead-lag records.

The positive 10-symbol cross-sectional funding result is excluded because its tradable universe is outside the fixed four-symbol contract. Positive execution proxies and records explicitly marked non-rank-eligible remain outside the strategy ranking with their reasons recorded rather than being silently discarded.

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

The slower Coinbase institutional-flow branch PR #159 was closed before any scientific result because it duplicated the faster Coinbase spot-to-Bybit dependency. The retained active path is `CLM-20260726-1935-ML-COINBASE-SPOT-001` / PR #155: one Coinbase BTC spot-flow displacement, one calibrated ML router, 500/1,000-ms causal Bybit execution and one structural payoff. Exact-arrival cross-venue V5D also remains active but its latest run stopped during source-frame preparation before a decision-ready economic result.

Reported work has rejected the tested first-passage, leverage-positioning, option-flow, option-surface, L2 hazard, L2 sweep-router, wallet-skill, parent-cadence and adjacent completed-bar dependencies under their recorded contracts. They do not receive threshold, feature, risk or leverage rescue.

## Current objective

Consume the retained fast Coinbase spot-flow ML result and corrected exact-arrival cross-venue result as soon as they become decision-ready. A positive hard-valid result is inserted into the cumulative ranking immediately under normalized conditions; a negative result is retired immediately. Do not spend the remaining research budget polishing ranked failures.

## Current blockers

Every positive raw rank remains far below the 1% target and has material concentration, sample, cost or sequential-robustness defects. No candidate has survived sequential selection with robust cost, concentration and regime behavior. Capital velocity remains low, and exact historical queue/depth execution is incomplete.

## Next exact action

Finish the retained Coinbase 500/1,000-ms source correction and frozen ML screen in PR #155, then consume the exact-arrival V5D output. If neither produces cost-surviving incremental information, switch the primary information source or payoff rather than retuning their models, thresholds, stops, risk rates or leverage.
