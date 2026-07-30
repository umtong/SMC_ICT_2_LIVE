# Failed-rejection double-trap continuation

**Claim:** `CLM-20260730-FAILED-REJECTION-CONTINUATION-001`  
**Result:** `RES-20260730-FAILED-REJECTION-CONTINUATION-001`  
**Decision:** `RETIRED_2022_FAILED_REJECTION_CONTINUATION_FAILURE`

## Logic

A previous-day high/low is raided, then a completed five-minute reclaim back inside makes the common sweep-reversal premise visible. The full raid extreme is frozen. If a later completed five-minute close rebreaks that extreme before the prior-day midpoint is delivered, the rejection itself has failed; reversal traders are trapped and their stops are the hypothesized payer for renewed external delivery.

## Programization correction

The first local implementation could assign a raid occurring several days later to an old next-day setup. Before economic use, the level interaction was corrected so the initial raid must occur during the level's own next UTC trade day. Subsequent reclaim/rebreak resolution remained structural and had no elapsed-time liquidation. The event search was vectorized without changing semantics.

## Corrected result

The final tape contained 574 resolved events: 295 BTC and 279 ETH.

At 24 bp:

- 2021: 228 trades, NAV 0.828990x, PF 0.587, median -0.2120%, exact winner-rerouted 0.684068x;
- 2022: 211 trades, NAV 0.873194x, PF 0.666, median -0.2020%, exact winner-rerouted 0.728318x.

The route was broad and negative. It did not fail because of a few absent jackpots or because fees alone erased a tiny positive surface.

## Interpretation

A completed rejection failure identifies trapped reversal inventory, but the trapped cohort's stop flow does not by itself guarantee that price can continue to the next external pool. The opposite side can absorb that flow or new value can form before the target. A valid continuation logic also needs observable liquidity withdrawal/low resistance ahead, not merely a known trapped cohort behind.

Calendar 2023, ML, risk/leverage and official 2024-2026 remained sealed. No reclaim-count, session, buffer, target-family, FVG/OB/MSS, asset-side, lower-cost or sizing rescue is authorized. No credentials or orders.
