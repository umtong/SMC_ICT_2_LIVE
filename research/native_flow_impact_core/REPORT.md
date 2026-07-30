# Native initiative-flow transport/absorption Core — fatal screen

**Result:** `RES-20260730-NATIVE-FLOW-IMPACT-CORE-001`  
**Claim:** `CLM-20260730-1930-NATIVE-FLOW-IMPACT-CORE-001` / issue #603  
**Decision:** **RETIRED_FATAL_SCREEN_NOT_CORE**; official 2024 remained sealed.

## Economic mechanism

The event removed chart-level geometry. A completed 30-second native Bybit window had to contain unusually large turnover relative to the prior-only 60-minute distribution and at least 60% signed-turnover imbalance.

- Efficient same-direction price impact represented initiative inventory transporting price and the `CONTINUE` action.
- Large initiative flow with poor progress or late opposite flow represented absorption/trapped takers and the `REVERSE` action.
- `FLAT` remained explicit.

The account used fixed 500 ms activation, the first later native observation, structural stop, 1.5R target, actual signed funding, 12/18/24 bp, 0.5% loss budget, 3x cap, one global slot and no elapsed-time close.

## Breadth

| Month | BTC events | ETH events |
|---|---:|---:|
| 2023-01 | 1,476 | 1,389 |
| 2023-04 | 1,412 | 1,517 |
| 2023-07 | 1,713 | 1,731 |
| 2023-10 | 1,386 | 1,706 |
| 2023-12 | 1,272 | 1,546 |

The fit set contained 18,435 resolved action rows and confirmation contained 11,805. The result is not event-sparse.

## Confirmation at 24 bp

| Policy | Trades | Multiple | PF | Median trade | MDD |
|---|---:|---:|---:|---:|---:|
| CONTINUE | 725 | 0.234503x | 0.339 | -0.5000% | 76.55% |
| REVERSE | 706 | 0.247292x | 0.350 | -0.5000% | 75.37% |
| Direct action-value ML | 0 | 1.000000x | — | — | 0% |
| Future oracle | 581 | 4.648134x | — | +0.2277% | 0% |

The future action is strongly separable ex post. The causal state is not sufficiently informative: the model assigned no positive expected value to any confirmation action. Constant negative predictions make rank correlation undefined, which is economically the same flat decision rather than evidence of a useful selector.

## Decision

Native initiative-flow intensity and impact efficiency alone do not identify a cost-surviving Core under this structural account contract. This is neither a frequency failure nor a missing-level problem. Adding prior-day levels, balances, FVG/OB/MSS gates or model complexity would change the frozen information unit and repeat the project's rescue pattern.

Retire this exact family. Do not alter the 30-second window, z/imbalance event, cooldown, barrier geometry, side/session, model, risk or leverage. No credentials, paper orders or live orders were used.
