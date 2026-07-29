# DST-aware ICT Silver Bullet causal screen

- Claim: `CLM-20260730-SILVER-BULLET-TAKEOVER-001`
- Result: `RES-20260730-ML-SILVER-BULLET-001`
- Decision: **TESTED_BELOW_GATE**
- Official 2024-2026 opened: **no**
- Orders: **none**

## Transcript-grounded interpretation

The New York 03:00-04:00, 10:00-11:00 and 14:00-15:00 windows were treated as opportunity context, not as a directional signal. This follows Chartbro's warning that time regularity is error-prone in Bitcoin. A trade required a one-sided raid and reclaim of the preceding three wall-clock hours, a completed break of a pre-known internal swing, and the first same-direction one-minute FVG.

Pending proximal and consequent-encroachment orders activated after 500 ms and expired only if still unfilled at the window end. A filled position had no elapsed-time close. Bybit funding, one global BTC/ETH slot, 0.5% planned risk, 3x notional cap and 12/18/24 bp paths were applied.

## Base evidence

- base events: **1,223**
- initial action rows: **2,446**
- resolved rows: **1,124**
- 2021 fit rows: **351**
- 2022 forward rows: **387**

Raw 2022 account paths:

- proximal: **7,569.95 USDT** at 18 bp, 196 trades;
- CE: **8,108.39 USDT** at 18 bp, 150 trades.

Every window, direction and entry mode had negative mean and median cost-after utility. New York AM was relatively less negative, but did not become positive.

## Programization audits

### FVG invalidation versus protected structure

The initial engine exited most positions when a completed one-minute close crossed the FVG far edge. Replaying the same fills with only the raid-extreme structural stop and liquidity target did not rescue the family. The best model path had 48 trades and ended at **9,686.75 USDT** at 18 bp and **9,532.42 USDT** at 24 bp; exact winner deletion ended at **8,948.20 USDT**.

### Internal versus external liquidity objective

A second action set added the nearest still-unconsumed confirmed internal swing beyond the MSS, while retaining the opposite pre-window range as the external objective. The action model received both targets rather than forcing the far target.

The best path had 59 trades and ended at **9,531.96 USDT** at 18 bp and **9,383.66 USDT** at 24 bp; winner deletion ended at **8,742.49 USDT**. No path survived.

## Final judgment

DST handling, one-sided raid ordering, pre-known swing confirmation, MSS timing, FVG construction, pending-order expiry, structural stops, internal/external targets, exact funding and the global slot were all represented causally. Removing the strongest plausible implementation objections did not produce positive broad account economics.

The exact Silver Bullet family is retired. The time windows may remain contextual features inside a materially different price-delivery system, but they are not an independent Bybit alpha.
