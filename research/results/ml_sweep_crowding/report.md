# ML Sweep/Crowding State Transition Result

- Result ID: `RES-20260727-ML-SWEEP-CROWDING-001`
- Claim: `CLM-20260727-0245-ML-SWEEP-CROWDING-001`
- Status: **SOURCE_GATE_FAIL**
- Contract SHA-256: `8fdbeb5840a5ec2b1c3029aa089e0aed6cbdffdcc11b2b02273b2a580a937f63`
- Live orders: none

## Mechanism

A completed external-liquidity sweep creates two mutually exclusive candidates: leveraged continuation through the level and absorption/reversal back through it. The fixed pooled HGBT uses completed Bybit price/volume state and one-observation-delayed Binance USD-M positioning/flow to choose one action or abstain.

## Pre-2024 decision

No pre-2024 account result opened: `BTCUSDT event-level delayed metric availability 76.69% below 90%`

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
