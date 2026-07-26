# Signed finalized Uniswap source

The primary source for this claim is the finalized canonical Uniswap V3 Swap-log stream for the USDC/WETH 0.05% pool. The immutable cumulative-state snapshot remains a reference-only identity and coverage cross-check because it ends before the strategy cutoff and does not preserve signed Swap amounts.

`amount0 > 0` with `amount1 < 0` means USDC entered and WETH left the pool, so completed WETH purchase pressure is positive. The opposite signs are completed WETH sale pressure. Events are identified by block number, transaction hash and log index, aggregated to completed UTC hours, and become usable two complete hours later.

The source gate downloads the complete signed stream from 2021-07-01 through 2023-12-31. It opens only two fixed one-day windows in 2024H1 to verify schema and transport continuity. It opens no Bybit market label, model, action, trade, PnL or complete official-period source.

A source pass authorizes the single preregistered HGBT stage. A positive pre-2024 cost path freezes sizing with information through 2023-12-31 and then opens the complete 2024H1 source and account immediately. A structurally weak 2024H1 result retires the information unit rather than adding another gate or tuning the failed dependency.
