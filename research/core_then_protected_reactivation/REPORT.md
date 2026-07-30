# Full Core realization then protected-delivery reactivation

**Result:** `RES-20260730-CORE-THEN-PROTECTED-REACTIVATION-001`  
**Status:** `RETIRED_UNCHANGED_2023_REACTIVATION_POLICY_BELOW_GATE`  
**Official 2024–2026:** unopened  
**Orders:** none

## Economic logic

The parent high-volume 96-hour accepted-delivery event contains two economically different opportunities:

1. a repeatable `+1.5R` Core realization; and
2. a later protected-delivery Expansion after a completed same-direction hour promotes the consumed external boundary.

This policy does not retain a partial runner. The original position is closed in full at `+1.5R`. A new Expansion position may be opened only after new causal information — boundary promotion — is available. Each leg pays its own cost and funding and is sized from then-current NAV. While an event merely waits for promotion, it reserves no global slot.

## Programization corrections and parity

The initial local implementation was quarantined because the unchanged-2023 Core path produced 104 rather than 106 trades. The mismatch was traced to two implementation defects:

- protected-boundary reacceptance before `+1.5R` was omitted, leaving twelve 2023 events open until the disaster stop;
- exact-timestamp one-slot arbitration used a score instead of the parent authority's stable time/symbol ordering.

After correction:

- all `599` parent event keys, entries, exits, stops, funding returns and exit semantics match the reproducible PR #550 Core authority;
- 2022 Core at 24 bp exactly reproduces `74` trades and `1.087013552582x`;
- unchanged 2023 Core exactly reproduces `106` trades and `1.054355269687x`;
- five focused causal/account tests pass.

The PR #597 compressed source carrier remains truncated/corrupted and cannot independently recover its nearby authority, so the reproducible PR #550 event/account semantics are the parent authority for this audit.

## 2022 forward screen at 24 bp

| Account | Trades | Multiple | PF | Median trade | MDD | Top-five positive-PnL share |
|---|---:|---:|---:|---:|---:|---:|
| Core only | 74 | 1.087014x | 1.544 | 0.4484% | 1.90% | 15.14% |
| Reactivation only | 21 | 1.086432x | 3.849 | 0.1076% | 1.38% | 69.17% |
| One-slot combined | 66 | 1.133619x | 2.158 | 0.2737% | 1.60% | 27.74% |
| Combined after exact parent-winner deletion/rerouting | 69 | 1.045255x | 1.322 | -0.0782% | 3.70% | 22.27% |

Both half-years were positive. The frozen 2022 gate passed.

## Unchanged 2023 confirmation at 24 bp

| Account | Trades | Multiple | PF | Median trade | MDD | Top-five positive-PnL share |
|---|---:|---:|---:|---:|---:|---:|
| Core only | 106 | 1.054355x | 1.232 | -0.0671% | 4.38% | 11.29% |
| Reactivation only | 27 | 1.076162x | 1.996 | -0.3934% | 3.17% | 94.83% |
| One-slot combined | 82 | 1.190830x | 1.966 | -0.1082% | 2.54% | 52.50% |
| Combined after exact parent-winner deletion/rerouting | 84 | 1.087102x | 1.441 | -0.1174% | 2.73% | 42.38% |

Both half-years and exact winner-deleted NAV remained positive. However, the combined median trade was `-0.1082%`, and the reactivation leg had a `-0.3934%` median with `94.83%` of positive PnL supplied by the top five winners. The deterministic policy therefore still earns much of its incremental value from long-duration Expansion tails rather than establishing a stable frequent Core.

## Decision

The exact reactivation policy is retired under its frozen contract. Official 2024–2026, risk/leverage selection and ML remain closed. The result is not a loss of the parent Expansion authority; it shows that cleanly separating full Core realization from a later new Expansion trade improves pre-2024 account behavior but does not yet produce the missing steady-compounding day-trading engine.

Do not tune the R target, promotion state, costs, symbol sides, risk, leverage, or add a partial runner/ML after this result.
