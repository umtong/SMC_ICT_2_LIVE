# Direct-utility Core lifecycle and universality audit

**Result:** `RES-20260730-DIRECT-CORE-LIFECYCLE-UNIVERSALITY-AUDIT-001`  
**Decision:** target not met; no ranking or live-permission change.

## Why this audit was required

The project requires a winner-independent, repeatable day-trading Core and a separate Expansion layer. The current protected-boundary rank-one route is a long-duration Expansion. The execution-aligned direct-utility route is the strongest available low-concentration Core evidence, so this audit tested whether its remaining weakness came from lifecycle programization or lack of universal economic information.

## Exact base reproduction

The exact reconstructed source selected `q=0.99` under the frozen pre-2024 chronology.

| Cost | Multiple | g/day | Trades | PF | MDD | Median hold | Top-10 positive share |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 15 bp | 1.205888x | 0.020530% | 473 | 1.1441 | 5.66% | 156m | 5.19% |
| 18 bp | 1.153637x | 0.015672% | 473 | 1.1101 | 6.00% | 156m | 5.18% |
| 24 bp | 1.060896x | 0.006482% | 473 | 1.0456 | 7.47% | 156m | 5.20% |

At 15 bp, deleting the top 10% positive candidates before complete slot rerouting still ended at `1.162567x`. This is not a jackpot-only path. It is nevertheless weak relative to the 1%/day target and later half-years do not compound steadily.

## Audit 1 — entry score reused as an exit score

The only pre-2024 survivor exited when the opposite side's predicted entry utility dominated. It improved 2022 and stayed positive in unchanged 2023, but official 15 bp fell to `1.162383x` / `0.016500% per day`, below the unchanged base. Entry action value is not hold value.

## Audit 2 — direct hold-versus-exit value model

A separate HGBT estimated the value of continuing versus immediately closing at 15/30/60/120/240/480 minutes using current state, progress in R, remaining stop/target distance, elapsed time and risk geometry. Out-of-year correlation decayed from `0.322` to `0.146`. Official 15 bp ended at `1.139793x`, and 24 bp at `1.004986x`; both were below the unchanged lifecycle.

## Audit 3 — readable state-rule extraction

Nested trend, crowding opposition, peer confirmation, range position, volume, premium and OI rules were replayed through the same account contract. The least-bad fixed rule still ended 2022 at `3414.64` USDT over `1265` trades. No rule survived. The ML edge cannot be honestly rewritten as a simple SMC checklist.

## Audit 4 — four-asset universality

One pooled model without symbol identity was trained on normalized BTC/ETH/SOL/XRP state and direct 24 bp action value. Every 2022 threshold lost money. The least-negative route was `q=0.995`, NAV `9291.28`, `161` trades, PF `0.845`; winner deletion and rerouting was also negative. Calendar 2023 and official 2024-2026 remained sealed.

## Decision

The current weak Core is not failing because one obvious exit rule is missing. Its observable state has insufficient stable information to price continuation versus exit, and its positive BTC/ETH behavior does not generalize to the four-asset universe. More lifecycle thresholds, SMC nouns, risk, leverage or asset-specific exceptions would repeat the project's earlier failure pattern.

The next research family must have a different payer and a fixed-small-risk gross edge that exceeds realistic costs before ML or portfolio sizing. The current protected-boundary route remains Expansion only; the reproduced direct-utility route remains weak Core evidence only.
