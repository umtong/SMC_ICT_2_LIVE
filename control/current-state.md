# Current state

- revision: 5
- phase: ACTIVE_RESEARCH
- Champion: `CHAMPION-20260725-HIGH-RESISTANCE-SWEEP-C232AE43`
- Champion stage: `EXPLORATORY`
- target_status: `NOT_MET`
- live_order_permission: none
- repository: `umtong/SMC_ICT_2_LIVE`
- Drive root: resolved privately through `config/project.local.toml` or `00_PROJECT_BINDING`

## Current Champion

The current research Champion is the `high_resistance_sweep` specification `c232ae43b7a1401d` from `RES-20260725-ALPHA-HYP-001` / PR #10.

- 12 bps base-cost geometric daily growth: `0.0024555%`
- target fraction: `0.24555%` of the 1% daily target
- total return: `+1.8076%`
- maximum drawdown: `7.2774%`
- trades: `55`
- profit factor: `1.0896`
- top-five positive-trade share: `66.92%`
- return at 18 bps: `-0.6401%`
- return at 24 bps: `-2.6322%`

It is the current comparison leader, not a validated or practical-use strategy. Its main weaknesses are cost fragility, profit concentration, small sample, no opened selection interval, and incomplete normalization against other studies.

The current execution component leader is `RES-20260725-1510-L1-EXEC-001`, which showed a positive relative routing improvement but negative standalone expectancy.

## Active work

Material active claims currently cover:

- causal alpha wave 1 across six mechanism families;
- spot/perpetual leadership and price discovery;
- exact funding-settlement behavior;
- flow-size and price-impact efficiency states;
- folder/action lifecycle reconciliation.

Reported work has rejected completed-bar cross-asset lead-lag, fixed BTC OI-shock families, transcript-derived five-minute formulations, and liquidity-sweep engulfing first-touch variants under their tested dependencies. These negative results remain reusable evidence.

## Champion policy

Champion means the current best hard-valid strategy or portfolio candidate. Target attainment, validation stage, and practical-use readiness are reported separately. A new material strategy result must be compared with the current Champion, and the Champion is updated whenever the new candidate is superior under normalized or explicitly qualified conditions.

`Champion: none` is used only before any comparable hard-valid candidate exists or when every available candidate is hard-invalid.

## Efficiency gates

- Read Project State and Champion first, then search only records related to the intended scope.
- Use Work Claims for costly or reusable work, not for short local checks.
- Apply staged validation: fast fatal-error screening, expanded validation for promising candidates, full stress only for material Champion challenges and practical-use candidates.
- Register only sources actually used or likely to be reused.
- Use full Run Reports and PRs only for material checkpoints or shared reusable changes.

## Current objective

Continue the highest-value unresolved strategy, execution, and account-path research. Replace the current Champion whenever a better hard-valid candidate appears, while preserving the explicit gap to the 1% daily target.

## Current blockers

The Champion is far below target and fails higher-cost stress. No candidate has yet survived sequential out-of-sample selection with robust cost and concentration behavior.

## Next exact action

Finish or materially advance the active spot-perp, funding-settlement, flow-size-impact, and causal-alpha claims. Compare each resulting strategy candidate with the current Champion rather than asking only whether it meets the final target or full validation threshold.
