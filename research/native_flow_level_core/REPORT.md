# Native Bybit microflow × repeated prior-day liquidity — fatal-screen report

**Result:** `RES-20260730-NATIVE-FLOW-LEVEL-STATE-CORE-001`  
**Claim:** `CLM-20260730-1832-NATIVE-FLOW-LEVEL-STATE-CORE-001` / GitHub issue #579  
**Decision:** **RETIRED_FATAL_SCREEN_NOT_CORE**; 2024 remained sealed.

## Mechanism

The previous completed UTC-day high and low were frozen for the immediately following day. Causally rearmed 15-minute interactions started competing `BREAK` and `REJECT` actions. Native Bybit sparse 500 ms trades measured outward aggressive-flow imbalance, price-impact efficiency, late flow reversal, trade intensity and no-trade density over the completed interaction bar and the final 120/30/5 seconds. OI, account ratio, funding and BTC/ETH peer state remained causal context.

This is not a FVG/OB/MSS checklist. It asks whether native initiative flow makes the outside price efficient and accepted, or is absorbed and rejected.

## Frozen chronology and account

- Fit: 2023-01, 2023-04, 2023-07.
- Confirmation: 2023-10, 2023-12.
- Official 2024-2026: sealed unless confirmation produced broad cost-net Core evidence.
- Fixed 500 ms activation; first later observable one-minute open.
- Symmetric stop/target at one structural scale around the frozen level; no elapsed-time close.
- Actual signed funding, adverse same-minute ambiguity, 12/18/24 bp.
- Fixed 0.5% NAV loss budget, 3x cap, one global slot.

## Event inventory

| Month | BTC | ETH | Total |
|---|---:|---:|---:|
| 2023-01 | 36 | 51 | 87 |
| 2023-04 | 56 | 54 | 110 |
| 2023-07 | 67 | 63 | 130 |
| 2023-10 | 46 | 41 | 87 |
| 2023-12 | 50 | 60 | 110 |

The confirmation population contained **382 resolved counterfactual actions**. It was not event-sparse.

## Unconditional 2023-10/12 one-slot policies at 24 bp

| Action | Trades | Multiple | PF | Median | MDD |
|---|---:|---:|---:|---:|---:|
| BREAK | 127 | 0.805824x | 0.362 | -0.4890% | 19.42% |
| REJECT | 127 | 0.835620x | 0.426 | -0.0474% | 16.74% |
| Future oracle | 107 | 1.298754x | — | 0.1802% | 0.00% |

The large, broad oracle shows that the future action is separable ex post. Both causal unconditional actions are strongly negative.

## Programization comparison

| Model | Confirm Spearman | Positive predictions / actions | 24 bp trades | Multiple | PF | Winner-deleted reroute |
|---|---:|---:|---:|---:|---:|---:|
| Price/OI baseline | 0.1570 | 3 / 382 | 3 | 0.999217x | 0.847 | 0.996060x |
| + native 500 ms microflow | 0.1897 | 3 / 382 | 3 | 0.993536x | 0.354 | 0.990042x |

Native microflow improved confirmation rank correlation from **0.1570** to **0.1897**, but did not create useful breadth. It predicted positive value for only **3 of 382** actions and its three selected trades lost at 12, 18 and 24 bp. This is the same sparse-model rescue failure as the prior completed-bar level model, not a viable Core.

## Decision and lesson

The implementation corrected the missing information clock: initiative flow and price impact were measured natively at 500 ms before entry. The result remained economically negative. Therefore poor prior results cannot be attributed solely to coarse 15-minute programization.

The exact information unit — previous-day high/low repeated interaction plus native 500 ms flow — is retired. Do not rescue it with a different window, level scale, rearm rule, threshold, model, FVG/OB gate, risk or leverage. The next family must change the economic source of Core alpha rather than refine this level family.

No credentials, paper orders or live orders were used.
