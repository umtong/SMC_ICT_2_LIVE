# Prior-day liquidity-interaction fatal screen

**Result:** `RES-20260730-PRIOR-DAY-LIQUIDITY-INTERACTION-FATAL-001`  
**Claim:** `CLM-20260729-ML-LIQUIDITY-INTERACTION-AV-001`  
**Verdict:** `RETIRED_EXACT_PRIOR_DAY_INTERACTION_FATAL_SCREEN`

## Question

At a causally frozen prior UTC-day high or low, does the first interaction have usable cost-after action value when acceptance and rejection are treated as competing states rather than assuming a sweep reversal?

This is the initial deterministic fatal screen for issue #399. It is intentionally broader than an SMC checklist and opens no ML, risk or official-period work unless one raw action has repeatable cost headroom.

## Fixed causal actions

- **Acceptance continuation:** after the first penetration, require two consecutive completed five-minute closes beyond the frozen prior-day boundary. Enter after fixed 500 ms at the first strictly later observable one-minute open. The protected interaction origin is the stop; full realization is `+1.5R`; a later completed five-minute close back inside is a state exit.
- **Rejection reversal:** before two-close acceptance, the first completed five-minute close back inside authorizes reversal. Stop is one basis point beyond the excursion extreme known at decision time; target is the frozen prior-day midpoint; renewed completed acceptance outside is a state exit.
- One global pending/open BTC/ETH slot, adverse same-minute stop priority, exact signed funding, fixed `0.5%` NAV planned loss and `3x` cap.
- No elapsed-time, scheduled or stage-boundary strategy close.
- Canonical Bybit 2021–2023 data only. 2024–2026 was not opened.

## Programization correction

The preliminary annual diagnostic had a real stage-boundary defect: an unresolved position could be omitted from an annual path, while an entry-year position whose structural exit occurred in a later year could be valued using that later price.

`CORRECTION-20260730-PRIOR-DAY-STAGE-BOUNDARY-MARK-001` changes only annual evaluation semantics:

- search stop, target and state exits only before the UTC year boundary;
- mark unresolved positions at the last observed pre-boundary one-minute close;
- apply funding only through the boundary;
- retain the global slot through the boundary;
- never treat the boundary mark as a strategy exit.

The corrected implementation is `run_boundary_corrected.py`; focused tests prohibit later-year target use and prohibit backdating a state exit executable exactly at the boundary. The correction did not change the economic verdict.

## Corrected 24-bp annual paths

| Action | Year | Trades | NAV multiple | PF | Median account return | Boundary marks | Winner-deleted/rerouted |
|---|---:|---:|---:|---:|---:|---:|---:|
| Acceptance | 2022 | 225 | 0.763773x | 0.539 | -0.3129% | 1 | 0.745855x |
| Acceptance | 2023 | 191 | 0.782656x | 0.503 | -0.3007% | 0 | 0.759488x |
| Rejection | 2022 | 325 | 0.556983x | 0.477 | -0.4941% | 0 | 0.500270x |
| Rejection | 2023 | 341 | 0.570321x | 0.501 | -0.4572% | 1 | 0.488615x |

Every 2022 and 2023 action remains negative even at 12 bp. Exact deletion of the largest 10% of positive event keys followed by full global-slot rerouting worsens every path.

## Corrected continuous 2021–2023 account

At 24 bp:

- acceptance: 651 trades, `0.516758x`, PF `0.619`, median `-0.3000%`, exact winner-deleted/rerouted `0.457441x`;
- rejection: 951 trades, `0.205388x`, PF `0.521`, median `-0.4943%`, one unresolved boundary mark, exact winner-deleted/rerouted `0.141524x`.

## Interpretation

The first prior-day high/low interaction is not itself a sufficient information source.

- Two outside closes do not distinguish durable sponsored acceptance from late continuation entry.
- A first reclaim does not distinguish exhausted forced flow from a temporary retracement.
- The raw action distribution is already negative and median-loss dominated, so ML would mainly learn abstention or rare historical tails.
- Risk, leverage, extra SMC gates and ML are therefore closed for this exact implementation.

This result does **not** claim all liquidity interaction is useless. It rejects this specific prior-day boundary plus two-close acceptance / first-reclaim action map. A new study must add materially different information—such as an external balance-sheet flow or a directly observed inventory transition—not another confirmation count, session or threshold.

No credentials or orders were used.
