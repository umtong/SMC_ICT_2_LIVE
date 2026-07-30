# Prior-day liquidity-interaction fatal screen

**Result:** `RES-20260730-PRIOR-DAY-LIQUIDITY-INTERACTION-FATAL-001`  
**Claim:** `CLM-20260729-ML-LIQUIDITY-INTERACTION-AV-001`  
**Verdict:** `RETIRED_EXACT_PRIOR_DAY_INTERACTION_FATAL_SCREEN`

## Question

At a causally frozen prior UTC-day high or low, does the first interaction have usable cost-after action value when acceptance and rejection are treated as competing states rather than assuming a sweep reversal?

This is the initial deterministic fatal screen for issue #399. It is intentionally broader than an SMC checklist and opens no ML, risk or official-period work unless one raw action has repeatable cost headroom.

## Fixed causal actions

- **Acceptance continuation:** after the first penetration, require two consecutive completed five-minute closes beyond the frozen prior-day boundary. Enter after the fixed 500 ms delay at the first strictly later observable one-minute open. The protected interaction origin is the stop; full realization is `+1.5R`; a later completed five-minute close back inside is a state exit.
- **Rejection reversal:** before two-close acceptance, the first completed five-minute close back inside authorizes reversal. Stop is one basis point beyond the excursion extreme known at decision time; target is the frozen prior-day midpoint; renewed completed acceptance outside is a state exit.
- One global pending/open BTC/ETH slot, adverse same-minute stop priority, exact signed funding, fixed `0.5%` NAV planned loss and `3x` cap.
- No elapsed-time, scheduled or stage-boundary strategy close.
- Canonical Bybit 2021–2023 data only. 2024–2026 was not opened.

## Main result

Neither action had sufficient gross headroom. At fixed account sizing, every 2022 and 2023 path was negative even at 12 bp. The 24-bp results were:

| Action | Year | Trades | NAV multiple | PF | Median account return | MDD | Winner-deleted/rerouted |
|---|---:|---:|---:|---:|---:|---:|---:|
| Acceptance | 2022 | 225 | 0.759006x | 0.533 | -0.3204% | 25.24% | 0.741201x |
| Acceptance | 2023 | 191 | 0.782656x | 0.503 | -0.3007% | 24.06% | 0.759488x |
| Rejection | 2022 | 325 | 0.556983x | 0.477 | -0.4941% | 46.10% | 0.500270x |
| Rejection | 2023 | 340 | 0.570031x | 0.501 | -0.4680% | 43.43% | 0.488366x |

The same actions were negative at 12 and 18 bp. Deleting the largest 10% of positive event keys before fully rerouting the global slot worsened every path.

## Interpretation

The first prior-day high/low interaction is not itself an alpha source.

- Two outside closes do not distinguish durable sponsored acceptance from late continuation entry.
- A first reclaim does not distinguish true forced-flow exhaustion from a temporary retracement.
- The raw action distribution is already negative and median-loss dominated, so a classifier would mainly learn to abstain or select rare historical tails.
- Risk, leverage, extra SMC gates and ML are therefore closed for this exact implementation.

This result does **not** claim that all liquidity interaction is useless. It rejects this specific prior-day boundary plus two-close acceptance / first-reclaim action map. A new study must add materially different information—such as an external balance-sheet flow or a directly observed inventory transition—not merely another confirmation count, session or threshold.

No credentials or orders were used.
