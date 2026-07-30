# Intrinsic-time internal-to-external liquidity delivery

**Claim:** `CLM-20260730-INTRINSIC-LIQUIDITY-DELIVERY-001`  
**Result:** `RES-20260730-INTRINSIC-LIQUIDITY-DELIVERY-001`  
**Decision:** `RETIRED_2022_INTRINSIC_LIQUIDITY_DELIVERY_FAILURE`

## Logic

A large volatility-normalized directional-change process represented the external delivery leg. A four-times-finer process represented internal liquidity. Inside the large direction, a new same-side micro extreme consumed internal liquidity; the first causal micro reversal back into the large direction entered toward the frozen large-leg extreme, with the swept micro extreme as stop and a large-scale reversal as state loss.

No FVG, OB, MSS, session, fixed timeframe, RR or ML gate was used.

## Result

The fixed scale generated 14,035 resolved events. It was not sparse:

- BTC: 7,289 candidates;
- ETH: 6,746 candidates.

At 24 bp:

- 2021: 5,840 trades, PF 0.167, median -0.4637%, median hold four minutes, account multiple 0.000000346x;
- 2022: 6,373 trades, PF 0.0456, median -0.4657%, median hold four minutes, account multiple 0.00000000783x.

Exact winner deletion and rerouting remained worse.

## Interpretation

Replacing clock bars with directional-change events did not itself recover the SMC/ICT hierarchy. A macro threshold equal to one average completed 15-minute range created tens of thousands of nominal macro legs and classified minute noise as external order flow. This is a semantic failure of the frozen scale definition, not a reason to tune its coefficient after outcomes.

A meaningful higher-order draw must be defined by an actually formed balance, a protected origin and a still-unconsumed destination. Volatility can normalize that geometry but cannot create its economic scale.

Calendar 2023, ML, risk/leverage and official 2024-2026 remained sealed. No threshold, scale ratio, confirmation, target/stop, session, SMC gate, asset-side, lower cost or sizing rescue is authorized. No credentials or orders.
