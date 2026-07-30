# Scale-CSD low-resistance delivery — research-exposed diagnostic

**Result:** `RES-20260730-SCALE-CSD-LOW-RESISTANCE-DELIVERY-001`  
**Decision:** `RETIRED_2022_NEGATIVE_SPARSE_OR_WINNER_DEPENDENT`  
**Ranking:** unchanged  
**Orders/live:** none

## Logic

After a causally active scale-matched four-hour pool is consumed, the same-color approach run's open is frozen as CSD reference. A completed four-hour body takeover in the opposite direction establishes control transfer. The first strict CSD repricing is the entry; at least two still-active one-hour pools must lie between entry and the still-active four-hour destination, and those pools are hold-through context rather than repeated realization points.

## Programization boundary

- right-confirmed 1h/4h pools and one-minute first-consumption timestamps;
- first encountered pool per sweep, no clustered duplicate event;
- target live through executable entry;
- pending strict trade-through occupies the global slot and cancels on premise loss or destination-first passage;
- fixed 500ms/next observed minute, actual funding, adverse same-minute ordering;
- fixed 0.5% current-NAV planned loss, 3x cap, 12/18/24bp;
- no elapsed-time or stage-boundary strategy close.

## Result

- resolved candidates: 712; filled: 489.
- 2021 / 24bp: 68 trades, 1.043197x, PF 1.661, median -0.0604%, winner-rerouted 0.974808x.
- 2022 / 24bp: 69 trades, 0.975423x, PF 0.562, median -0.0410%, winner-rerouted 0.955867x.

The 2021 ordinary path was positive but negative-median and winner-dependent. The untouched 2022 path was negative at every cost. Calendar 2023, ML, risk/leverage and official 2024-2026 remained sealed.

## Decision

This implementation corrects the earlier mistake of treating low-resistance pools as repeated scalp targets, but the more faithful CSD control-transfer entry and hold-through lifecycle still lacks repeatable Core value. No adjacent CSD/pool/scale/target/stop/FVG-OB-MSS/model/cost/risk/leverage rescue is authorized.
