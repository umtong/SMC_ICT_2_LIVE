# Repeated prior-day liquidity-level survival hazard — decision report

**Result:** `RES-20260730-ML-LEVEL-HAZARD-TAKEOVER-001`  
**Decision:** `RETIRED_2022_NO_BREADTH_SURVIVOR`  
**Ranking/live:** unchanged; no orders.

A completed prior-day high/low was treated as a live liquidity pool. Causally separated revisits updated level age, touch number, prior rejection, penetration and approach state. A pooled standardized logistic model estimated outward versus inward structural first passage, then routed breakout, rejection or flat by direct 18-bp expected R. The chosen event/action tape was replayed unchanged at 12 and 24bp with actual funding, fixed 0.5% NAV risk, 3x cap and one global slot.

## Programization

- 18 event families and 54 structural geometries;
- 1,296 frozen model/threshold policies;
- same-side clustered levels de-duplicated to the closest level; both-side touches ambiguous;
- level availability only after the prior UTC day completed;
- touch numbering independent of payoff width;
- one-use retirement and year-boundary marking;
- cost-invariant decisions and exact global-slot routing.

## Untouched 2022

No policy survived the registered breadth gate.

The best ordinary 18-bp diagnostic shrank to 37 trades: `1.083322x`, PF 1.679, median `-0.4573%`, 24-bp `1.040117x`, top-five share 58.43%.

The best route with at least 100 trades made 106 trades but ended `0.969880x` at 18bp and `0.907114x` at 24bp, with PF 0.918/0.737 and median near `-0.466%`.

Across 1,296 policies, 139 were ordinary-positive at 18bp and 64 nonnegative at 24bp, but none combined at least 100 trades with positive 18/24-bp accounts. Threshold tightening selected a sparse negative-median tail rather than a repeatable Core. Calendar 2023, official 2024-2026, risk/leverage and adjacent SMC-gate rescue remained sealed.
