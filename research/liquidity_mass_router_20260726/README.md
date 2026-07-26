# Causal External Liquidity Mass Router

Claim: `CLM-20260726-1704-LIQUIDITY-MASS-001`

## Explanation to an SMC/ICT trader

The model draws a live map of unresolved **buy-side liquidity** above price and **sell-side liquidity** below price. Equal highs/lows, repeated confirmed pivots and confirmed hourly swings increase a pool's mass. Age and local traded volume increase visibility, but only information already confirmed at the decision close is used.

When price consumes a pool:

- **Sweep and reject:** if price raids the pool and closes back through it, trade toward the nearest sufficiently denser pool on the opposite side.
- **Sweep and accept:** if price closes directionally beyond the pool with displacement, trade the stop cascade toward the nearest sufficiently denser pool in the same direction.

Entry is the next 5-minute open. A rejection stop is beyond the raid extreme; an acceptance stop is behind the consumed pool and event extreme. The target is the frozen unresolved pool. There is no arbitrary time exit.

This is not an FVG/OTE delivery template and not the active ML nearest-pool first-passage model. Direction, stop and target are determined by the consumed-pool state and explicit pool-mass asymmetry.

## Staging

- 2022: 128-policy fit screen.
- 2023: downloaded only if fit survivors are frozen first.
- 2024–2026: prohibited by code.
- BTCUSDT, ETHUSDT, SOLUSDT and XRPUSDT; one global slot.
- Risk-based NAV sizing; identical candidates at 12/18/24 bps.
- Exact top-10% winner removal excludes decision keys before slot competition and replays from initial NAV.

A zero-survivor result retires this exact pool-mass translation rather than inviting adjacent tuning.
