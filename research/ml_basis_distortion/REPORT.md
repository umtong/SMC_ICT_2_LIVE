# Bybit basis-distortion lifecycle router — decision report

**Result:** `RES-20260730-ML-BASIS-DISTORTION-001`  
**Decision:** retired before 2023 confirmation; ranking unchanged.

## Hypothesis

A first crossing into a prior-only three-standard-deviation Bybit mark/index basis distortion was treated as exchange inventory stress. The position faded the distortion after the fixed 500 ms delay. ML selected between exit on causal basis-sign normalization, a protected-order-flow structural hold beyond normalization, and flat. Premium, OI, account ratio, turnover efficiency, multi-horizon trade/index divergence, peer BTC/ETH state and time-of-day were continuous evidence.

## Programization audit

- Every market entry is exactly the first later one-minute open, 60 seconds after the completed five-minute availability timestamp at this resolution.
- Fifteen-minute pivots become known only after two right-side bars. A pivot is not promoted as protected until a later completed close expands beyond the prior structure; same-close promotion is impossible.
- One global slot arbitrates simultaneous BTC/ETH events by predicted action value and blocks overlaps.
- Positions unresolved at the selection boundary are NAV-marked; there is no elapsed-time or scheduled close.
- The final runner stops after the failed 2022 gate. Calendar 2023 is not generated as evidence.

Four focused tests pass. The staged result is byte-deterministic across reruns.

## 2022 economics at 24 bp

Raw constant policies were both negative:

- basis normalization: **−19.42%**, 383 trades, PF 0.744, median −15.35 bp; winner deletion −38.46%;
- structural hold: **−14.41%**, 243 trades, PF 0.830, median −50 bp; winner deletion −44.55%.

ML did not produce a viable state-dependent policy:

| model | return | trades | PF | MDD | winner-deleted return |
|---|---:|---:|---:|---:|---:|
| ridge clipped value | −3.97% | 36 | 0.383 | 4.21% | −5.52% |
| HGBT clipped value | **−0.43%** | 96 | 0.984 | 7.25% | −21.61% |
| logistic positive-value | −0.73% | 92 | 0.956 | 7.24% | −10.81% |
| HGBT positive-value | −5.55% | 71 | 0.771 | 10.13% | −18.50% |

For the closest HGBT route, out-of-sample MAE was worse than a constant for both actions. Classifier Brier scores were worse than constant probabilities. No model passed the frozen gate requiring positive 18/24-bp paths, at least 30 trades, PF above one and positive exact winner deletion.

## Decision

The exchange-native basis distortion has a genuine inventory-normalization interpretation, but its cost-surviving action surface is negative in the 2022 selection period and the model has no reliable state discrimination. Calendar 2023 and official 2024-2026 remain unopened. No adjacent basis threshold, rolling horizon, stop, cost, risk or leverage rescue is justified.

No credentials, paper orders or live orders were used.
