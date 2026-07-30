# RES-20260730-PROTECTED-TRENDLINE-EXTERNAL-DRAW-CORE-001

## Logic

Protected trendline break and first opposite-side retest, continuation toward a true unconsumed external draw.

BTCUSDT and ETHUSDT are test markets; the economic mechanism is the thesis. The evaluator uses causal completed structure, fixed 500 ms activation represented by the first strictly later one-minute open, actual funding, one global slot, fixed 0.5% NAV planned loss, 3x cap, adverse same-minute ordering and no elapsed-time strategy close.

## Programization audit

- External targets are only still-unconsumed prior-day, prior-week or causally confirmed four-hour pools.
- The structural stop uses the full observed event excursion, not only the final confirmation bar.
- Targets and stops must remain beyond executable entry; dominated actions are flat.
- Exact winner events are removed before complete global-slot rerouting.

## 2022 fatal screen

| Path | Trades | Multiple | PF | Median | H1 | H2 | Top-5 share |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0 bp | 567 | 0.744538x | 0.8436 | -0.4635% | -9.82% | -17.44% | 44.87% |
| 24 bp | 567 | 0.186847x | 0.3544 | -0.5000% | -51.74% | -61.28% | 52.15% |
| 24 bp top-5 deleted/rerouted | 565 | 0.141366x | 0.1759 | -0.5000% | -63.49% | -61.28% | 33.17% |

## Decision

The continuation action was broadly negative even before cost after correcting target semantics and full retest-excursion invalidation. It is an economic failure, not a sparse or execution-only failure.

Calendar 2023, ML, risk/leverage research and official 2024-2026 remained sealed. No credentials, paper orders, testnet orders or live orders were used.

## Reproduction

- evaluator SHA-256: `beb5923b95113bdb9b945076a8ce040ca2e0271b229f773708dceca862395234`
- result SHA-256: `48c7da791e0002497760457e1fea65b908d73a097ed1a7864003a75b454a59f4`
- summary SHA-256: `baae61956878807d79769a1e1df1733d1dd198ae0713c6a11e1f274331409998`
