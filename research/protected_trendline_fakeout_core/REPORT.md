# RES-20260730-PROTECTED-TRENDLINE-FAKEOUT-CORE-001

## Logic

Failed protected-trendline break: reclaim old side before break-side external liquidity, then reverse toward the opposite external draw.

BTCUSDT and ETHUSDT are test markets; the economic mechanism is the thesis. The evaluator uses causal completed structure, fixed 500 ms activation represented by the first strictly later one-minute open, actual funding, one global slot, fixed 0.5% NAV planned loss, 3x cap, adverse same-minute ordering and no elapsed-time strategy close.

## Programization audit

- External targets are only still-unconsumed prior-day, prior-week or causally confirmed four-hour pools.
- The structural stop uses the full observed event excursion, not only the final confirmation bar.
- Targets and stops must remain beyond executable entry; dominated actions are flat.
- Exact winner events are removed before complete global-slot rerouting.

## 2022 fatal screen

| Path | Trades | Multiple | PF | Median | H1 | H2 | Top-5 share |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0 bp | 495 | 1.251970x | 1.2965 | -0.0895% | 13.84% | 9.98% | 21.76% |
| 24 bp | 495 | 0.573350x | 0.4900 | -0.2052% | -17.08% | -30.86% | 32.78% |
| 24 bp top-5 deleted/rerouted | 492 | 0.495553x | 0.3342 | -0.2065% | -25.56% | -33.43% | 19.28% |

## Decision

The fakeout action had a broad, low-concentration gross edge, but completed-reclaim market entry consumed the entire headroom. It is not a cost-surviving Core and does not authorize 2023.

Calendar 2023, ML, risk/leverage research and official 2024-2026 remained sealed. No credentials, paper orders, testnet orders or live orders were used.

## Reproduction

- evaluator SHA-256: `f98bf5c85b39d417c158655e5db384172565f0a5fb3b42560f887ebc0cb1d59a`
- result SHA-256: `7df42ba6e3005b73973822802adac85a55e98c05815a650c7e364e3f5560a67c`
- summary SHA-256: `fcefb282ad0c63afc71c8d3e7611b3a17a10bb64c546bfd7db4db768d7dd156b`
