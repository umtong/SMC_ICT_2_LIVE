# Prior-day value reentry passive-entry programization audit

## Decision

`RES-20260730-VALUE-REENTRY-PASSIVE-AUDIT-001` is `RETIRED_PASSIVE_UPPER_BOUND_FAILURE`.

The parent failed-auction rotation was unusually broad and non-concentrated at zero cost, so testing whether immediate marketable entry destroyed the logic was justified. The exact parent source was recovered and reproduced before the variant was interpreted.

## Frozen mechanism

- Freeze the previous complete UTC day’s 64-bin turnover-at-price profile, contiguous 70% value area, VAH/VAL and POC.
- After an auction outside value and the first later completed five-minute close back inside, keep the original excursion stop, POC target and outside-reacceptance state exit.
- Replace only the marketable entry with a pending order at the frozen VAH/VAL boundary.
- Pending occupies the single global slot and cancels only on POC delivery, structural stop, outside reacceptance, or data boundary; no elapsed-time cancellation.
- Evaluate a perfect boundary-touch fill upper bound and a stricter 1 bp penetration variant.

## Parent parity

- Complete profiles: BTC 1,095; ETH 1,022.
- Resolved events: 2,083; global-slot trades: 1,888.
- Continuous 2021–2023: zero-cost NAV 11,270.67; 12 bp 1,862.17; 18 bp 1,051.02; 24 bp 662.11.
- These match the published parent authority.

## Perfect boundary-touch upper bound

| Year | Cost treatment | Trades | NAV multiple | PF | Median trade | Winner-deleted multiple |
|---:|---|---:|---:|---:|---:|---:|
| 2022 | zero entry fee + only half of 12 bp on exit | 510 | 0.616691x | 0.366 | -0.0819% | 0.469935x |
| 2022 | 12 bp total | 510 | 0.509617x | 0.252 | -0.1187% | 0.408819x |
| 2022 | 24 bp total | 510 | 0.397324x | 0.143 | -0.1745% | 0.341462x |
| 2023 | zero entry fee + only half of 12 bp on exit | 547 | 0.568193x | 0.386 | -0.1142% | 0.407764x |
| 2023 | 12 bp total | 547 | 0.423007x | 0.235 | -0.1642% | 0.331727x |
| 2023 | 24 bp total | 547 | 0.301100x | 0.112 | -0.2293% | 0.263421x |

Even the impossible favorable case with a perfect boundary fill and zero entry-side fee ended at 0.6167x in 2022 and 0.5682x in 2023. The strict 1 bp trade-through variant was no better.

At 24 bp, the perfect-touch fills had negative gross instrument return before non-price cost: −2.85 bp mean in 2022 and −1.72 bp in 2023. Median holding time was five minutes. Most trades exited because value was reaccepted outside again (376/510 in 2022; 396/547 in 2023), not because queue modeling denied favorable fills.

## Interpretation

The broad zero-cost parent tendency was not a hidden passive-entry Core. Waiting for the first rebalance at VAH/VAL selected auctions that rapidly failed back outside; the post-fill action surface itself was negative. Exact queue position, partial fill and maker rebate can only worsen or marginally shift an already negative upper bound.

## Boundary

- Retire this exact passive-entry family.
- Do not tune the limit offset, penetration requirement, profile bins, value-area percentage, state exit, target, stop, symbol/side, cost, risk, leverage or add ML.
- 2024–2026 remains unopened; no credentials or orders were used.
