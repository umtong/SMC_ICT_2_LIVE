# SMT Overreaction MSS Reclaim

Claim: `CLM-20260726-1530-SMT-OVERREACTION-RECLAIM-001`  
Issue: `#116`

## SMC/ICT explanation

1. **Displacement:** a completed BTC impulse with abnormal activity and aligned aggressive flow establishes the current delivery direction.
2. **External-liquidity run:** SOL or XRP follows BTC but moves materially farther than its prior-only BTC beta implies.
3. **SMT divergence:** the follower has delivered beyond fair relative value. The residual gap is measured directly rather than drawn after the fact.
4. **CISD / MSS:** the main policy does not blindly fade strength. It waits for residual contraction and a completed one-second flip in follower aggressive flow.
5. **Entry:** take the opposite side after 100 or 300 ms.
6. **Target:** residual equilibrium reclaim, defined as 75% closure of the initial divergence.
7. **Invalidation:** continued overdelivery, additional adverse follower displacement, or loss of the original BTC displacement state.

There is no elapsed-time forced exit. A source-boundary unresolved path receives a full stop.

## Frozen evidence boundary

The parent PR #87 established only that the overreaction opportunity exists: 121 events at 12 bp and 61 at 24 bp across four untouched December 2023 dates. It did not compute strategy PnL. This claim freezes entry, exit, cost, routing and account rules before opening four different pre-2024 dates.

## Candidate set

Six policies only:

- immediate fade control versus MSS-confirmed reclaim;
- minimum divergence of 12, 18 or 24 bp.

Every policy is replayed at both 100 and 300 ms and at 12, 18 and 24 bp. The 2024-2026 periods are mechanically sealed.
