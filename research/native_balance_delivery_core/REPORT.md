# Native compressed-balance acceptance/rejection Core — fatal screen

**Result:** `RES-20260730-NATIVE-BALANCE-DELIVERY-CORE-001`  
**Claim:** `CLM-20260730-1852-NATIVE-BALANCE-DELIVERY-CORE-001` / issue #590  
**Decision:** **RETIRED_FATAL_SCREEN_NOT_CORE**; 2024 remained sealed.

## Mechanism

A prior-only eight-bar/two-hour balance with directional path efficiency no greater than 0.35 and range no greater than 1.25 times the prior-only 30-day median two-hour range represented two-sided inventory. The first unambiguous 15-minute interaction with one boundary started competing outward `ACCEPT` and inward `REJECT` actions. The decision close had to remain within 0.15 frozen balance widths of the boundary to avoid chasing a completed move.

Native Bybit sparse 500 ms initiative flow and price-impact efficiency were measured before entry. This is balance liquidity accumulation → boundary consumption → acceptance or failed auction → delivery, not a generic breakout or SMC checklist.

## Breadth

| Month | BTC | ETH | Total |
|---|---:|---:|---:|
| 2023-01 | 73 | 83 | 156 |
| 2023-04 | 116 | 112 | 228 |
| 2023-07 | 134 | 130 | 264 |
| 2023-10 | 91 | 113 | 204 |
| 2023-12 | 111 | 114 | 225 |

The confirmation population contained **855 resolved action rows**, so the failure was not caused by too few events.

## Unconditional 2023-10/12 one-slot result at 24 bp

| Action | Trades | Multiple | PF | Median | MDD |
|---|---:|---:|---:|---:|---:|
| ACCEPT | 293 | 0.568737x | 0.362 | -0.5000% | 43.48% |
| REJECT | 259 | 0.496393x | 0.227 | -0.5000% | 50.50% |
| Future oracle | 179 | 1.684295x | — | 0.2740% | 0.00% |

The ex-post oracle was broad and positive, but both causal actions were strongly negative.

## ML programization audit

| Model | Fit Spearman | Confirm Spearman | Positive confirm predictions | 24 bp trades |
|---|---:|---:|---:|---:|
| Price/OI baseline | 0.3359 | 0.0931 | 0 / 855 | 0 |
| + native 500 ms microflow | 0.3626 | 0.0874 | 0 / 855 | 0 |

Native flow marginally improved in-sample ranking but degraded confirmation ranking and assigned no positive action value in confirmation. The model correctly collapsed to flat because the economic action surface was negative; this is not a useful Core policy.

## Decision

This failure is stronger than the repeated prior-day-level result. A frequent intraday balance event population existed, and the future action was separable ex post, but the available causal state did not identify it after costs. The exact two-hour compressed-balance information unit is retired. Do not rescue it with balance length, compression threshold, entry proximity, structural geometry, feature window, model complexity, SMC gates, risk or leverage.

No credentials, paper orders or live orders were used.
