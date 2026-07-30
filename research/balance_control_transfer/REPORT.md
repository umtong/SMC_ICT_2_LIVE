# Causal balance-to-balance control-transfer policy

**Claim:** `CLM-20260730-BALANCE-CONTROL-TRANSFER-001`  
**Result:** `RES-20260730-BALANCE-CONTROL-TRANSFER-001`  
**Decision:** `RETIRED_PROGRAMIZATION_CORRECTED_PRE2024_ECONOMIC_FAILURE`

## Logic tested

The symbols were treated only as testbeds. The economic thesis was that a completed two-sided auction accumulates liquidity at both edges; the first edge expansion consumes that liquidity and attracts breakout inventory; later value established outside transfers control and supports continuation, while reacceptance inside traps breakout inventory and supports rotation to old equilibrium. Entry and exit followed the same state premise. FVG, OB, MSS, session and indicator names were not gates.

## Programization defect and correction

The first implementation called every completed prior UTC day a balance. That mislabeled directional trend days as two-sided auctions. The corrected balance identity required: (1) day open and close inside the completed 70% value area; (2) both UTC half-days trading on both sides of the completed POC. Five focused semantic tests passed.

Only 228 BTC and 172 ETH completed days satisfied that identity, versus 1,095/1,022 complete days.

## Corrected one-packet result

At 24 bp in calendar 2022:

- acceptance: 92 trades, NAV 0.8279x, PF 0.378, winner-rerouted 0.7525x;
- rejection: 30 trades, NAV 0.9515x, PF 0.413, winner-rerouted 0.9340x.

The route was frequent enough to diagnose and broadly negative, not a few-winner failure.

## Expansion -> rebalance -> redelivery audit

A second frozen implementation waited for two equal-turnover post-break packets. Acceptance required the first packet outside, a two-sided second packet around the first packet VWAP, and same-direction redelivery while still outside old value. Rejection required the second packet to reestablish value inside the old balance. No threshold grid was opened.

At 24 bp in calendar 2022:

- acceptance: 19 trades, NAV 0.9944x, PF 0.877, winner-rerouted 0.9564x;
- rejection: 49 trades, NAV 0.9009x, PF 0.223, winner-rerouted 0.8783x.

Acceptance improved toward break-even at lower cost but was sparse, negative at 24 bp and failed exact winner deletion. Calendar 2023 and official 2024-2026 remained sealed by the frozen gate.

## Interpretation

The auction logic remains coherent, but the chosen observable is insufficient. Price/turnover location says where business occurred; it does not identify whether the business was fresh opening inventory, closing flow, passive absorption, or trapped leverage. The next information unit must estimate the cost basis of fresh leveraged inventory from signed aggressive trades and OI, then test whether that inventory is protected or trapped.

No ML, risk/leverage search, adjacent profile/sensor threshold, lower cost, asset-specific exception, official interval, credential or order was opened.
