# Causal SMC/ICT Liquidity Sweep → MSS → OTE

Claim: `CLM-20260726-1603-OTE-SWEEP-001`  
Stage: pre-2024 fatal alpha screen; not rank eligible.

## Explanation for an SMC/ICT trader

This is a direct translation of a classic ICT entry model into timestamped rules.

1. **External liquidity** is the prior completed 5- or 15-minute-equivalent rolling high/low, implemented as the prior 300 or 900 seconds.
2. A completed 5s/15s bar **raids** that level but closes back inside.
3. Within three or six bars, price closes through the opposite frozen internal structure level. That is the causal **market-structure shift**.
4. The raid extreme and MSS close define a fixed **dealing range**. The move must be true displacement relative to prior volatility and aggressive flow.
5. A resting entry is placed at the fixed **Optimal Trade Entry** retracement: 62%, 70.5%, or 79%.
6. A touch is not enough. An actual trade must pass the level by one observed tick.
7. The stop is beyond the raid extreme. The target is the opposing external-liquidity level already known when MSS confirmed.

There is no future pivot confirmation, hand-picked swing, BPR/FVG requirement, discretionary premium/discount drawing, or elapsed-time exit.

## Why it is a new payoff unit

The completed BPR screen required two opposing FVGs and their overlap. This study requires neither FVG nor overlap. Its edge must come from a deep retracement into the raid-to-displacement dealing range after a causal structure shift.

It also excludes active breaker/Unicorn, inversion-FVG, FVG-SMT and session claims.

## Frozen screen

- Official Bybit BTCUSDT and ETHUSDT public trades.
- Completed 5s and 15s bars.
- Fit: 2023-01-15, 2023-03-19, 2023-05-21.
- Conditional development: 2023-07-16, 2023-09-17, 2023-11-19.
- 96 fixed candidates.
- One global BTC/ETH position.
- Same paths replayed at 12, 18, and 24 bps.
- Counterfactual top-winner removal reroutes the global slot.
- 2024-2026, funding refinement, BBO audit, risk and leverage remain unopened until a robust pre-2024 survivor exists.

Zero fit survivors retires this exact sweep-MSS-OTE dependency; adjacent Fibonacci levels are not tuned.
