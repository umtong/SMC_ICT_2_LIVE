# Current state

- revision: 7
- phase: ACTIVE_RESEARCH
- current first place: `FIRST-20260725-HIGH-RESISTANCE-SWEEP-C232AE43`
- first-place stage: `EXPLORATORY`
- target_status: `NOT_MET`
- live_order_permission: none
- repository: `umtong/SMC_ICT_2_LIVE`
- Drive root: resolved privately through `config/project.local.toml` or `00_PROJECT_BINDING`

## Current strategy ranking

The current first place is the `high_resistance_sweep` specification `c232ae43b7a1401d` from `RES-20260725-ALPHA-HYP-001` / PR #10.

- 12 bps base-cost geometric daily growth: `0.0024555%`
- 1% target gap: `0.9975445 percentage points per trading day`
- target fraction: `0.24555%`
- total return: `+1.8076%`
- maximum drawdown: `7.2774%`
- trades: `55`
- profit factor: `1.0896`
- top-five positive-trade share: `66.92%`
- return at 18 bps: `-0.6401%`
- return at 24 bps: `-2.6322%`

It is first because it currently has the smallest verified after-cost geometric daily-growth gap among ranked hard-valid strategy results. The ranking is provisional and low-confidence because windows, markets, and cost contracts are not fully normalized.

The current execution-routing component first place is `RES-20260725-1510-L1-EXEC-001`, which improved modeled execution drag but has negative standalone expectancy.

## Pending closer candidate

PR #25 candidate `021fbab613517a31ad98` reports `0.0571%` after-cost geometric daily growth, positive returns at 12/18/24 bps, 194 trades, PF `1.502` and MDD `4.63%`. Its observed gap to the 1% target is smaller than the current first place and it would become provisional first if hard-valid evidence completes.

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
- dynamic common-factor residual verification and flow-conditioned continuation/absorption;
- conditional reconciliation of the folder/action lifecycle change.

Reported work has rejected causal alpha wave 1, exact funding-settlement families, completed-bar cross-asset lead-lag, fixed BTC OI-shock families, transcript-derived five-minute formulations, and liquidity-sweep engulfing first-touch variants under their tested dependencies. These negative results remain reusable evidence.

## Current objective

Continue the highest-value unresolved strategy, execution and account-path research. Choose work independently of current rank. When a result becomes decision-ready, rank it by closeness to the full objective and update the table.

## Current blockers

The current first place is far below target, fragile to higher costs, concentrated in a small number of trades, and has no opened selection interval. The economically closer PR #25 candidate cannot enter the ranking until its failed reproducibility workflow is repaired. No candidate has survived sequential out-of-sample selection with robust cost and concentration behavior.

## Next exact action

Repair and rerun PR #25 immutable-bundle verification while materially advancing the active spot-perp and flow-size-impact claims. Rank any decision-ready result by objective proximity after hard-valid evidence is complete.
