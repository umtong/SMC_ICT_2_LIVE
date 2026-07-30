# Higher-order reversal converts an opposing swing ladder to low-resistance liquidity

**Claim:** `CLM-20260730-LIQUIDITY-LADDER-CONVERSION-001`  
**Result:** `RES-20260730-LIQUIDITY-LADDER-CONVERSION-001`  
**Decision:** `RETIRED_2022_LIQUIDITY_LADDER_CONVERSION_BELOW_BREADTH_GATE`

## Logic

During the old higher-order trend, the monotone one-hour opposing swing ladder is layered resistance. After consumption of a scale-matched confirmed four-hour external pivot and a completed four-hour structure shift, the still-unconsumed ladder changes role. A completed fifteen-minute body close beyond rung `j` was treated as acceptance through low-resistance liquidity and entered toward rung `j+1` or the final active four-hour external target.

This did not use first-pullback, inducement raid, FVG, OB, OTE or session gates.

## Programization audit

The first event implementation started the old-leg ladder at the last four-hour pivot broken by the reversal. That left only the short interval immediately before the shift and nearly erased the intended pre-existing staircase. Before economic judgment, the window was corrected to start at the prior scale-matched four-hour swing that began the old leg.

Additional causal rules:

- all pivots usable only after two completed right-side bars;
- external and ladder liquidity retired on first later completed one-minute consumption;
- a target touched before the body-acceptance decision was invalid;
- latest causal fifteen-minute opposite pivot, bounded by the four-hour protected origin, was the stop;
- empty winner-deletion routes remained valid zero-trade paths.

## Result

The final tape contained 60 resolved actions after 715 completed four-hour reversals across BTC and ETH.

At 24 bp:

- 2021: 27 trades, NAV 1.002463x, PF 1.055, median +0.0921%, winner-rerouted 0.981285x;
- 2022: 19 trades, NAV 0.999923x, PF 0.998, median +0.0900%, median hold 451 minutes, winner-rerouted 0.995880x.

At 18 bp, 2022 reached 1.002435x and PF 1.070, but deleting its two largest positive event keys before full one-slot rerouting reduced NAV to 0.990537x.

## Interpretation

The transcript-grounded resistance-role conversion is directionally meaningful: unlike broad first-pullback and inducement families, its median trade remained positive and its 24-bp path reached break-even. However, the event is too rare and the small total edge depends on a few deliveries. It cannot be the missing frequent Core, and the 2022 gate did not authorize 2023.

Do not rescue with pivot radius, rung count, body threshold, scale, passive retest, target/stop, session, FVG/OB/MSS, symbol-side, lower cost, ML, risk or leverage. No credentials or orders.
