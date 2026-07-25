# Liquidation Refill V1

`CLM-20260726-0500-LIQUIDATION-REFILL-001` tests a forced-flow state transition that is intentionally different from ordinary trade-tape bursts, passive maker fills, two-sided movement-hazard OCO orders, cross-venue propagation, and completed-bar SMC/ICT patterns.

The hypothesis has two branches:

1. **Cascade continuation** — follow the liquidation side only when observed liquidation notional accelerates, same-side dominance is high, price impact is efficient, and the completed event minute closes near its directional extreme.
2. **Exhaustion reversal** — fade the liquidation side only after the burst is followed by a completed confirmation minute with strong deceleration and price recovery away from the liquidation extreme.

All decisions use Tardis `local_timestamp` capture order. Continuation enters at the next minute open after the completed event minute. Reversal waits for a completed confirmation minute and enters at the following minute open. Stops are outside the causal event range; targets are fixed multiples of the planned stop distance. There is no time-based forced liquidation. If neither stop nor target is reached inside the downloaded path, the trade remains unresolved and the candidate cannot pass.

The first screen uses only the publicly downloadable first day of each month. Fit is 2021-09 through 2022-12, development is 2023, and 2024 remains unopened unless a preregistered development gate passes. This sparse sample is discovery evidence only, never a full-period target result.

A critical source limitation is preserved rather than “corrected”: since 2021-04-27 Binance's public forced-order stream is a maximum one-order-per-second snapshot. Observed notional is therefore a lower bound. The strategy never treats the feed as complete liquidation volume.
