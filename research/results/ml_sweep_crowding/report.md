# ML Sweep/Crowding State Transition Result

- Result ID: `RES-20260727-ML-SWEEP-CROWDING-001`
- Claim: `CLM-20260727-0245-ML-SWEEP-CROWDING-001`
- Status: **SOURCE_GATE_FAIL**
- Contract SHA-256: `2677f51b0fce67e5550920796edc248f5119fa2dfddc0067cd38fef5e8b4de8a`
- Live orders: none

## Mechanism

A completed external-liquidity sweep creates two mutually exclusive candidates: leveraged continuation through the level and absorption/reversal back through it. The fixed pooled HGBT uses completed Bybit price/volume state and one-observation-delayed Binance USD-M positioning/flow to choose one action or abstain.

## Pre-2024 decision

No pre-2024 account result opened: `BTCUSDT official static Bybit 1m coverage 90.631254% below 99.500000% from first observed 2021-01-01T00:00:00+00:00`

## Causality and execution

- Every signal uses a completed five-minute bar.
- Binance metrics are delayed by one complete observation.
- The fixed 500ms latency enters no earlier than the next observable one-minute open.
- Stop/target ambiguity is adverse-first; gap-through stops use the adverse open.
- Actual Bybit funding settlements are applied to signed notional.
- There is no time-based strategy exit; interval boundaries NAV-mark open exposure.
- One global slot is enforced across BTCUSDT and ETHUSDT.

## Decision

The frozen source/schema/coverage gate failed before an economic result opened. The exact route is closed without outcome inference.
