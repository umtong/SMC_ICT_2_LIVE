# Funding Cash-Transfer Notional × OI Reaction

## SMC/ICT explanation

This study makes the liquidity pool observable before the trade.

1. **Liquidity pressure** — actual transferred USDT is `abs(settled funding rate) × causal open interest × causal mark price`.
2. **Liquidity pool** — the funding sign identifies the payer side whose margin is debited and the receiver side whose margin is credited.
3. **Displacement / liquidity run** — post-settlement OI contraction with payer-direction price displacement is a closure cascade; OI expansion with the same directional displacement is receiver-side re-leveraging.
4. **Sweep exhaustion** — if OI and price already contracted before settlement, then the post-settlement extreme extends but OI contraction stalls and price reclaims, the liquidity run is treated as complete.
5. **Execution** — the sparse fatal screen waits one additional full bar and uses the first observed last price within one second. A survivor may later enter only on the first causal retracement into the displacement imbalance/FVG using exact Bybit BBO and depth.
6. **Invalidation** — continuation is invalidated by opposing reclaim or reversal of the OI state; reversal is invalidated by renewed payer-direction OI contraction and loss of the reclaimed level.

The vocabulary is familiar to SMC/ICT traders, but each state is computed from exchange-native, timestamped cash-transfer, OI and price information.

## Frozen stage

- Tardis normalized Bybit `derivative_ticker` monthly first-day samples.
- 2022 fit, 2023 development, 2024-2026 code-prohibited.
- BTCUSDT, ETHUSDT, SOLUSDT and XRPUSDT attempted; source-only eligibility.
- 512 fixed candidates and one global slot.
- Same gross path at 12/18/24 bp all-in round-trip cost.
- Sparse proxy only; no ranking or live-order permission.
