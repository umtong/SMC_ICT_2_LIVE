# Volume-sponsored causal swing-pool control-transfer result

- Result ID: `RES-20260730-CAUSAL-SWING-POOL-CONTROL-001`
- Status: `RETIRED_2022_DETERMINISTIC_ECONOMIC_FAILURE`
- 2021 pooled prior-only log-turnover-z q75: `0.6293676360`
- Causal candidate counts: `2021 451 / 2022 489 / 2023 514`
- Candidate states: `ACCEPT 1,084 / REJECT 370`
- Calendar-2022 eligible policies: none
- Official 2024-2026: unopened
- Credentials/orders: none

## Logic tested

A fully confirmed 4h swing was treated as a one-use external-liquidity pool. The first later 1h close through the outermost newly consumed pool on exceptional turnover began one control-transfer event. The immediately next completed 1h auction determined either outside-price acceptance continuation or inside-price rejection rotation. Entry, nearest still-unconsumed 4h target, hard invalidation and broken-level state loss followed that same premise.

This was a direct universality audit of the current volume-sponsored accepted-delivery logic: if the logic were general, it should survive replacement of the arbitrary 96h channel with causal higher-timeframe liquidity pools.

## Programization corrections before final interpretation

The first local output was quarantined. The final authority corrected and reran from scratch:

1. the 4h level must already be available before the consuming 1h bar begins;
2. the completed minute between decision and conservative first-later-minute entry cancels a setup if target, stop or premise was already consumed;
3. unresolved year-end positions are marked at the boundary and continue blocking the slot rather than using a later year's exit price;
4. post-2023 candidate generation remains sealed because no pre-2024 route survived.

Two fresh processes produced byte-identical `RESULT.json`, `REPORT.md` and `CANDIDATES.csv`.

## Principal 24bp paths

### Calendar 2022 untouched screen

- `FULL_MAP`: 263 trades, `0.911420x`, PF `0.8352`, median `-0.208309%`, MDD `10.01%`, winner-deleted/rerouted `0.820204x`.
- `ACCEPT_ONLY`: 212 trades, `0.875607x`, PF `0.6997`, median `-0.194379%`, MDD `13.85%`, winner-deleted/rerouted `0.804282x`.
- `REJECT_ONLY`: 99 trades, `0.965013x`, PF `0.8518`, median `-0.241547%`, MDD `7.34%`, winner-deleted/rerouted `0.874554x`.

Both 2022 half-years were negative for the full map and acceptance policy. Rejection was negative in H1 and weakly positive in H2. No policy passed the frozen gate.

### Unchanged 2023 diagnostic

2023 was not used to rescue or select a policy; it was retained only to diagnose whether the 2022 sign was accidental.

- `FULL_MAP`: 280 trades, `0.834838x`, PF `0.7064`, median `-0.195215%`, MDD `20.50%`, winner-deleted/rerouted `0.739066x`.
- `ACCEPT_ONLY`: 231 trades, `0.823773x`, PF `0.5989`, median `-0.187155%`, MDD `21.62%`, winner-deleted/rerouted `0.778458x`.
- `REJECT_ONLY`: 114 trades, `0.963368x`, PF `0.8777`, median `-0.267959%`, MDD `6.47%`, winner-deleted/rerouted `0.844770x`.

### Continuous 2022-2023

- `FULL_MAP`: 543 trades, `0.760889x`, PF `0.7723`, median `-0.199344%`, MDD `25.15%`, winner-deleted/rerouted `0.654689x`.
- `ACCEPT_ONLY`: 443 trades, `0.721302x`, PF `0.6512`, median `-0.189579%`, MDD `29.03%`, winner-deleted/rerouted `0.652846x`.
- `REJECT_ONLY`: 213 trades, `0.929662x`, PF `0.8661`, median `-0.256173%`, MDD `9.03%`, winner-deleted/rerouted `0.798473x`.

Median holding time was roughly three to four hours, so this is an adequately frequent day-trading failure rather than a sparse-tail result.

## Zero-cost diagnostic—not an executable strategy

The fixed route was also replayed at zero transaction cost only to separate weak gross information from execution cost:

- 2022 `FULL_MAP`: `1.076651x`; 2023: `1.052825x`.
- 2022 `REJECT_ONLY`: `1.043751x`; 2023: `1.086704x`.
- `ACCEPT_ONLY` remained below one in both years.

Thus rejection around consumed causal swing pools contained a small gross relation, but the median trade remained negative and realistic 12bp already reduced 2022 rejection to `0.999812x` and the full map to `0.983317x`. The signal has no cost headroom and no robust Core path.

## Economic interpretation

The failure is broad and reproducible. Exceptional turnover through **any single confirmed 4h swing** does not identify a sufficiently concentrated liquidity pool or durable control transfer. Most such pivots are ordinary structural waypoints. Acceptance frequently occurs late in an already mature move; rejection contains a small gross rotation tendency but not enough to pay for realistic execution.

This means the current positive 96h protected-boundary Expansion cannot yet be generalized as “volume sponsorship works at every causal liquidity pool.” Its value appears tied to a much broader, rarer external-boundary state and long price-delivery tails. A meaningful pool likely needs additional causal evidence of defended inventory or clustered stops, not another arbitrary pivot width or filter added after this outcome.

## Decision

`RETIRE_CAUSAL_SWING_POOL_CONTROL_TRANSFER_PRE2024`.

Do not rescue this exact family with another pivot width, turnover threshold, penetration amount, confirmation count, target, stop, symbol side, cost, risk, leverage, FVG/OB/session condition or ML filter. Ranking and live authority are unchanged.
