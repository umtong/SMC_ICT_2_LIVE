# Breaker / Mitigation Programization Audit

- claim: `CLM-20260730-ML-BREAKER-PROGRAM-AUDIT-001`
- result: `RES-20260730-ML-BREAKER-PROGRAM-AUDIT-001`
- hard validity: `PASS_PRE2024_CAUSAL_PROGRAMIZATION_AUDIT`
- economic status: `TESTED_BELOW_GATE`
- official 2024-2026 opened: no
- orders: none

## What was corrected

1. Block-close invalidation was separated from the distant sweep-extreme disaster stop for risk sizing.
2. MSS itself now confirms the running final swing; the engine no longer waits for an independent right-side p3 pivot and then searches for MSS.
3. Stop distance, target distance, reward/risk and range location are recalculated from the actual post-500ms entry rather than the MSS close.
4. Market-after-reaction was compared with passive midpoint/block-edge entries.
5. Conservative first-touch block/OTE orders were tested immediately after MSS.
6. The first first-touch result was invalidated because it inherited reaction-body, penetration and waiting-time fields observed after order submission. The final model excludes all post-order reaction fields.

## Final evidence

- 21,570 action rows;
- 12,987 base events;
- 11,629 resolved action rows;
- 432 final causal first-touch model/account paths;
- 56 nominally positive paths at 18bp;
- 41 nominally positive paths at 24bp;
- zero paths with at least 60 trades, positive 18bp NAV, nonnegative 24bp NAV, top-five positive-PnL share no more than 50%, and positive exact winner-deletion NAV.

Best final path retaining at least 60 trades:

- entry: first-touch block edge;
- model: HGBT, threshold 0.20;
- trades: 71;
- 12 / 18 / 24bp NAV: 10,323.41 / 9,932.02 / 9,610.64;
- PF at 18bp: 0.9590;
- median trade at 18bp: -30.79bp;
- top-five positive-PnL share: 56.15%;
- exact winner-deletion NAV: 8,038.20.

The direct breaker + FVG + OTE + aligned 1h structure rule produced 68 trades, 8,862.36 USDT at 18bp, PF 0.6323 and 8,241.17 USDT after winner deletion.

## Decision

Breaker events were generally less negative than matched mitigation events, so importing external stop liquidity did change the state in the expected relative direction. It did not create a standalone cost-surviving account edge. Every useful-breadth route remained negative or collapsed under 24bp and exact winner deletion; positive routes were sparse and tail-dependent.

The exact breaker/mitigation standalone family is retired without threshold, checklist, cost, risk, leverage or confidence-multiplier rescue. Breaker state may be reused only as context inside a materially different information unit.

The full source, tests and diagnostic grids were generated and validated in the research session. This draft branch currently carries compact decision evidence only; it must not be merged as a reusable implementation until the complete source bundle is transported and hash-verified.
