# Corrected 100 ms ICT Rejection Block result

## Decision

`RES-20260730-REJECTION-BLOCK-100MS-CORRECTED-001` is **RETIRED_CORRECTED_SOURCE_FREQUENCY_ECONOMIC_SCARCITY_AND_NEGATIVE_EDGE**.

The archived PR #102 result was hard-invalid because a 100 ms source was treated as 500 ms. This takeover reconstructed the SHA-bound evaluator and changed exactly two source-cadence assumptions, with no strategy, candidate, date, cost, risk, leverage, target, or account change.

## Frozen fit result

- candidate cells: 216
- candidates with at least one completed 24 bp trade: 96
- maximum trades in any candidate: 6
- frozen minimum required trades: 12
- fit survivors: 0
- conditional 2023 development opened: false

At 12/18/24 bp, the number of candidates with positive mean return was 0 / 0 / 0. The best eventful 24 bp candidate still had mean -20.385140 bp, median -20.842091 bp, PF 0.000000, and at most 6 trades.

## Interpretation

The programization defect was real: correcting source cadence restored events. It did not restore a tradable edge. The exact family is both too sparse for its frozen gate and negative even before any risk or leverage search. Calendar 2023 remained sealed because no fit survivor existed; official 2024-2026 remained unopened.

This resolves the earlier ambiguity correctly: the original zero-event run was invalid evidence, while the corrected run is valid negative evidence. The terminal-wick Rejection Block family should not be reopened through adjacent bar length, pool lookback, raid depth, wick ratio, displacement, entry fraction, session, target, cost, risk, or leverage changes.

## Reproduction evidence

- workflow run: `30480384939`
- workflow job: `90672700139`
- result artifact: `8735404989`
- artifact digest: `sha256:d7ed5d89d3892e92401fcfe714559e3cfd67ad601a1041fec1ede4c1c5dc224a`
- immutable source artifact: `8626169763`
- archived evaluator SHA-256: `ee0246361892131a0ae3638ec4cd23ae235f0513c8710dd70edcfb9b6918d166`
- corrected evaluator SHA-256: `49a36e929fecd7d57f41970314f6dd6adad8ab46b08971dbbdd97558b0939bcd`
- focused tests: 4 passed

## Boundary

No adjacent tuning, ML rescue, risk/leverage search, credentials, paper orders, or live orders were used.
