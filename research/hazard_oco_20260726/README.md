# Bybit movement-hazard OCO research

Claim: `CLM-20260726-0248-HAZARD-OCO-001`

This study changes the payoff structure rather than trying another ordinary directional threshold. It predicts only whether a material short-horizon move is imminent, then simulates two independent conditional market entries on **Bybit BTCUSDT USDT-linear perpetual**. The first trigger establishes direction; the opposite order remains live through explicit non-atomic cancellation latency and can create a whipsaw flattening loss.

## Causal contract

- Tardis `local_timestamp` is the sole information and execution clock.
- Features use completed 100 ms bins and end strictly before each five-second decision.
- An unchanged completed BBO may be carried for at most one second. Every accepted decision still requires a complete preceding 60-second state path; no feature or fit label bridges state older than one second.
- Market-entry acknowledgement and trigger-to-fill latency are explicit. A simulated fill requires a real executable quote event no more than 200 ms after its aligned fill boundary; state carry never creates a fill.
- Same-bin dual entry triggers become a full adverse round trip, and same-side retriggers cannot hide a later opposite trigger before cancellation becomes effective.
- Stop wins target ambiguity.
- No elapsed-time position liquidation exists. Positions leave only through target, stop or the preregistered hazard-decay/re-entry state rule. The two state-exit observations must be exactly five seconds apart.
- After an accepted entry, target, stop and state exits are searched only before the first unavailable BBO state. An unresolved position at that boundary or at the source-day end is not deleted or marked favorably; the candidate account is assigned terminal loss.
- 2025 selection and every 2026 file remain physically unopened unless a frozen development survivor exists.

## Evaluation boundary

Fit uses the public first-day samples for `2023-01-01` and `2023-07-01`. Development uses `2024-01-01` and `2024-07-01`. The 162 frozen policy cells are replayed at 12/18/24 bp and 100/300 ms cancellation latency. Exact top-10% winner removal releases the affected global slots and reruns the account from initial NAV for preliminary survivors.

The public sample cannot certify full-calendar daily growth. A positive result remains exploratory until independently reconstructed from official Bybit data or another independent source and then evaluated under the project's sequential 2024–2026 contract.

No credential, paper order, testnet order or live order is used.
