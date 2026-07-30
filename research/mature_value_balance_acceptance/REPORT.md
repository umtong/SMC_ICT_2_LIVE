# Mature multi-day value-balance sponsored acceptance — decision report

**Result:** `RES-20260730-MATURE-VALUE-BALANCE-ACCEPTANCE-001`  
**Decision:** `RETIRED_2022_SPARSE_OR_ECONOMIC_FAILURE`  
**Ranking/live:** unchanged; no orders.

## Logic

Two consecutive completed UTC days formed a mature balance only when both were genuine two-sided auctions and their completed 70% turnover value areas retained a non-empty common intersection. The first completed one-hour close outside the active frozen balance retired it. Only a close with the inherited accepted-delivery sponsorship threshold created a fixed `+1.5R` Core action; completed reacceptance inside the consumed edge was state loss.

BTC and ETH were testbeds. No symbol identity, side selection, FVG, OB, MSS, session, ML, risk grid or leverage search created the event.

## Programization

- completed-day profiles: 1,387;
- genuine two-sided days: 254;
- first outside expansions: 28;
- sponsored action events: 6;
- semantic checks: 4 passed.

The first outside close retired the balance whether sponsored or not; the engine could not wait for a later favorable break. Boundaries changed only at UTC-day open from completed days. Funding used the canonical mark at the actual event timestamp. One slot, adverse ambiguity and year-boundary marking were enforced.

## Economics at 24bp

- 2021: 3 trades, `0.994096x`, PF 0.510, median `-0.4979%`, winner-rerouted `0.987990x`.
- untouched 2022: 3 trades, `1.000484x`, PF 1.080, median `-0.1633%`, 2022H2 negative, top-five share 100%, winner-rerouted `0.993935x`.

The actual mature balance was too rare once its first expansion also had to carry exceptional completed business. Loosening the balance or waiting for a later sponsored break would change the mechanism into already-retired arbitrary-box or repeated-breakout families. Calendar 2023, ML, risk/leverage and official 2024-2026 remained sealed.
