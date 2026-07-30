# Four-asset idiosyncratic overshoot reversion Core

**Result:** `RES-20260730-XSEC-OVERSHOOT-REVERSION-CORE-001`  
**Decision:** `RETIRED_PRE2024_RESIDUAL_REVERSION_FAILURE`

## Question

An asset can temporarily move farther than the contemporaneous BTC/ETH/SOL/XRP common move because urgent local inventory is consumed first. The frozen rule faded a six-hour idiosyncratic residual only after it exceeded both two prior-only standard deviations and 1%, then exited on half-residual reversion, another half-residual extension, or a 2ATR/0.5% outer hard stop.

## Programization checks

- The four-asset common hourly grid is exact; six-hour windows crossing a gap are invalid.
- The 720-hour mean and standard deviation end before the event hour.
- The event hour must be completed, and entry occurs at the first one-minute open strictly after the 500ms activation boundary.
- Relative target/state-loss decisions use completed common five-minute closes and execute at the next one-minute open.
- Hard stops have adverse priority through the planned state-exit minute.
- Funding uses actual signed Bybit events and contemporaneous mark price.
- Removed winners are deleted by event identity before a complete one-slot reroute.

Synthetic symmetry, cost, chronology and state-transition checks passed. No threshold was changed after seeing the result.

## Opportunity and gross economics

The frozen event generator produced **1,421** events: 725 in 2022 and 696 in 2023. The one-slot zero-cost path completed 790 trades and ended **1.1051x**, PF **1.070**. Both years were mildly positive before costs, but the trade median was already slightly negative.

## Realistic-cost decision

| Cost | 2022 multiple | 2023 multiple | Continuous | Trades | PF | Winner-reroute continuous |
|---:|---:|---:|---:|---:|---:|---:|
| 12 bp | 0.9855x | 0.9053x | 0.8923x | 790 | 0.923 | 0.7770x |
| 18 bp | 0.9446x | 0.8579x | 0.8103x | 790 | 0.859 | 0.7091x |
| 24 bp | 0.9073x | 0.8159x | 0.7403x | 790 | 0.802 | 0.6510x |

At 24bp, the median holding time was **240 minutes** and the largest five winners supplied only **6.95%** of positive PnL. This is not a sparse-jackpot failure. It is a frequent, low-concentration mean-reversion tendency whose gross edge is smaller than realistic execution cost.

## Interpretation

Half-residual reversion occurred often enough to create a small zero-cost edge, but hard stops and extension losses consumed it. The relation also changed materially by symbol and side between 2022 and 2023, so selecting only favorable subgroups would be post-outcome symbol optimization rather than a universal market logic.

The exact family is retired without changing the six-hour horizon, z threshold, target fraction, state-loss fraction, stop, cost, symbol/side, model, risk or leverage. Official 2024-2026 remains unopened. The next Core must use information that is not already embedded in completed cross-asset prices.

No credentials, paper orders, testnet orders or live orders were used.
