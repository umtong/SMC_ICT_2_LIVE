# Fresh-inventory cost-basis protection/trap policy

**Claim:** `CLM-20260730-FRESH-INVENTORY-COST-BASIS-001`  
**Result:** `RES-20260730-FRESH-INVENTORY-COST-BASIS-001`  
**Decision:** `RETIRED_2022_FRESH_INVENTORY_COST_BASIS_FAILURE`

## Logic

A true old-balance edge is consumed. Fresh opening inventory was declared only when exact breakout-direction aggressive public-trade turnover dominated and completed OI increased. The aggressive-side VWAP was treated as the fresh inventory cost basis. The next equal-turnover packet classified that inventory as protected when price stayed outside and profitable with OI persistent, or trapped when price returned inside and crossed through the cost basis while OI remained elevated.

## 2022 fatal screen

At 24 bp / 0.5% current-NAV risk / 3x cap:

- protected continuation: 35 trades, NAV 0.895582x, PF 0.145, median -0.4752%, winner-rerouted 0.881915x;
- trapped reversal: 14 trades, NAV 0.977849x, PF 0.251, median -0.2132%, winner-rerouted 0.973420x.

No action survived. Calendar 2023, ML, risk search and official 2024-2026 remained sealed.

## Programization/observability conclusion

The logic requires ownership of newly opened inventory. Public aggressive-side VWAP plus net OI increase does not identify it: aggressive buys can be fresh longs or short covers, passive sells can be fresh shorts, and OI reports only the net pair count. The resulting cost basis is therefore not a causal cost basis of the party expected to become protected or trapped. This is an observability failure, not a threshold problem.

The exact family is retired without OI magnitude quantiles, cost-basis buffers, response windows, extra SMC gates, symbol-side exceptions, lower costs, ML, risk or leverage. No credentials or orders.
