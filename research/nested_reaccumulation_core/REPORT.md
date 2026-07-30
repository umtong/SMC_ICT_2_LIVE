# Nested reaccumulation inside accepted delivery

**Claim:** `CLM-20260730-NESTED-REACCUMULATION-CORE-001`  
**Result:** `RES-20260730-NESTED-REACCUMULATION-CORE-001`  
**Decision:** `RETIRED_2022_NESTED_REACCUMULATION_FAILURE`

## Logic

The higher-order context was not inferred from a generic trend. It was the exact positive protected-boundary accepted-delivery state: a high-volume external break followed by a later same-direction expansion that promoted the broken boundary.

Inside that state, equal-dollar-volume packets formed local two-sided balances. A same-direction packet break plus a second outside redelivery packet entered toward the nearest still-unconsumed, causally confirmed 15-minute swing liquidity. Stop was beyond the opposite balance edge; completed return inside the balance or loss of the parent state exited. No elapsed-time close existed.

## Programization correction

Overlapping parent states were made causal and non-duplicative: the latest promotion superseded the older state. Confirmed 15-minute liquidity pools were maintained as a live active set and retired on first later consumption; already consumed pivots could not be reused as targets.

## Result

The tape contained 468 resolved events.

At 24 bp:

- 2021: 180 trades, NAV 0.859323x, PF 0.468, median -0.0827%, median hold 20 minutes, winner-rerouted 0.802388x;
- 2022: 246 trades, NAV 0.873690x, PF 0.645, median -0.0870%, median hold 18 minutes, winner-rerouted 0.747546x.

Even 2022 at 12 bp ended 0.976838x. The short-hold surface was broad and negative rather than dependent on a few missing winners.

## Interpretation

A genuine multi-day delivery can coexist with negative economics in its smaller internal auctions. Repeatedly realizing each local continuation is not equivalent to holding the larger state. The parent Expansion is paid for tolerating intermediate adverse movement until a rare long delivery completes; it cannot be converted into steady Core simply by splitting it into nested balances.

Calendar 2023, ML, risk/leverage and official 2024-2026 remained sealed. No packet budget/count, balance geometry, swing definition, target/stop, session, FVG/OB/MSS, asset-side, lower cost or sizing rescue is authorized. No credentials or orders.
