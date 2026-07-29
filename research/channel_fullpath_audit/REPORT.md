# Exact Bybit channel full-path model/risk audit

**Result:** `RES-20260730-BYBIT-CHANNEL-FULLPATH-AUDIT-001`  
**Base result:** `RES-20260730-BYBIT-DONCHIAN-ML-FULLPATH-001`  
**Verdict:** `PROVISIONAL_EXPANSION_ALPHA_POSITIVE_SMALL_RISK_BOUNDED_EXACT_MODEL_ARTIFACT_MISSING`

## Decision

The published channel candidate remains the strongest provisional Expansion result, but it is not a complete system and is not deployment-ready. The event/execution geometry was independently reconstructed exactly; the exact ML model, scored candidate tape, trade ledgers, daily NAV files and run log were not retained as retrievable repository or workflow artifacts. They are present only as SHA-256 attestations.

## Exact parity reached

The independent canonical-Bybit reconstruction generated 2,855 events:

- 2021: 538
- 2022: 511
- 2023: 369
- 2024: 578
- 2025: 598
- 2026H1: 261

The annual training boundaries also match the published result exactly:

- 2024 model: 1,418 resolved rows; last release 2023-12-29 16:22 UTC
- 2025 model: 1,996 rows; last release 2024-12-30 17:43 UTC
- 2026 model: 2,594 rows; last release 2025-12-29 09:42 UTC

This makes a broad signal-generation or annual-label-boundary bug unlikely. The remaining uncertainty is the exact model and portfolio tape, not basic Donchian event geometry.

## Fixed-risk decomposition of the published path

The reported 13-bp path has 80 trades, 2.67849456x ending NAV, mean account return 2.571259% per trade, 5% planned loss and maximum leverage 7.4074x. Because maximum used leverage is below the 12x cap, reducing planned loss to 0.5% scales every continuous-quantity trade return by 0.1 without changing selected events or slot chronology.

For each trade return `r` and `t=0.1`:

```text
log(1 + t r) >= t log(1 + r)
log(1 + t r) <= t r
```

Therefore the exact 0.5%-risk path is bounded by:

- ending multiple: **1.103543x to 1.228386x**
- UTC daily geometric growth: **0.010804% to 0.022557%**

After the published exact top-10%-winner deletion and full slot rerouting:

- ending multiple: **1.028702x to 1.122095x**
- UTC daily geometric growth: **0.003103% to 0.012632%**

Thus the selected tape has positive small-risk value, including after winner deletion, but it is structurally far from 1%/day. The 5% risk choice amplifies the Expansion payoff and drawdown; it is not the Core information source.

The 2026H1 5%-risk multiple was 0.712426x. Under the same scaling assumptions, the 0.5%-risk multiple is bounded below by **0.966661x**, so the regime failure remains real but most of the 28.76% account damage is risk amplification.

## Independent nearby HGBT

A separately implemented HGBT mean/q35 blend used the same 2,855-event tape and exact annual release counts but not the unavailable exact model specification.

At 0.5% planned risk:

- 13 bp: **1.316704x**, **0.030173%/day**, 96 trades
- 24 bp: **1.245854x**, **0.024106%/day**

At 5% risk its 13-bp headline rose to **4.582131x**, but exact top-10%-winner deletion and rerouting fell to **0.802941x**. A model very close in concept therefore changes the selected tails enough to reverse robustness.

## Robust pre-2024 screen

A separate BASE-feature bootstrap ensemble trained direct 24-bp action value and used a lower-confidence bound `mean - k*bootstrap_std`, with `k` fixed from `{0, 0.25, 0.5, 0.75, 1.0, 1.5}`. Calendar 2021 trained the 2022 model; 2021-2022 trained 2023. There were **zero** routes that retained positive 24-bp NAV, nonnegative exact winner-deletion rerouting and meaningful breadth in both 2022 and 2023. Official 2024-2026 was not opened for this alternative.

This does not invalidate the published exact model. It demonstrates that the exact unavailable model artifact is decision-critical and cannot be replaced by a generic “similar HGBT” claim.

## Final use in the system

Preserve the exact reported path provisionally as an **Expansion component** only. It may compete for the global slot when its exact model and artifact are available. It is not a Core engine, is not target-compliant, and has no live authority.

Do not rescue it with 2026-aware thresholds, additional channel lookbacks, wider risk or greater leverage. The missing requirement is an independent, frequent, positive Core information source plus reproducible publication of the exact Expansion model and ledgers.
