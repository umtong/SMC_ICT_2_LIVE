# Current state

- revision: 6
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

- spot/perpetual leadership and price discovery;
- flow-size and price-impact efficiency states;
- dynamic common-factor residual and flow-conditioned continuation/absorption;
- conditional reconciliation of the folder/action lifecycle change.

Reported work has rejected causal alpha wave 1, exact funding-settlement families, completed-bar cross-asset lead-lag, fixed BTC OI-shock families, transcript-derived five-minute formulations, and liquidity-sweep engulfing first-touch variants under their tested dependencies. These negative results remain reusable evidence.

## Champion policy

Champion means the current best hard-valid strategy or portfolio candidate and is implemented as a rank pointer to an already registered result. Target attainment, validation stage, and practical-use readiness are reported separately. A new material strategy result is ranked against the current Champion, and the pointer is updated whenever the new candidate is superior under normalized or explicitly qualified conditions.

Champion status grants no research priority, protection budget, additional validation obligation, or default improvement path. Work selection follows expected contribution to the 1% objective and information value. Existing results remain available through ordinary Result Registry and version-control records, so Champion changes do not trigger repeated backup or revalidation work.

`Champion: none` is used only before any comparable hard-valid candidate exists or when every available candidate is hard-invalid.

## Efficiency gates

- Read Project State and Champion first, then search only records related to the intended scope.
- Use Work Claims for costly or reusable work, not for short local checks.
- Apply staged validation: fast fatal-error screening, expanded validation for promising candidates, and full stress only when a result can materially change strategy/account selection or practical-use decisions.
- Register only sources actually used or likely to be reused.
- Use full Run Reports and PRs only for material checkpoints or shared reusable changes.

## Current objective

Continue the highest-value unresolved strategy, execution, and account-path research. Choose work independently of Champion status; update the Champion pointer as a bookkeeping consequence when a superior hard-valid candidate appears.

## Current blockers

The Champion is far below target and fails higher-cost stress. No candidate has yet survived sequential out-of-sample selection with robust cost and concentration behavior.

## Next exact action

Finish or materially advance the active spot-perp, flow-size-impact, and dynamic-factor claims according to expected target contribution and information value. When a result becomes decision-ready, record it once, compare its rank with the current Champion, and update only the pointer if superior.
