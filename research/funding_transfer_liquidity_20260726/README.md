# Funding-Transfer Liquidity Engine

## SMC/ICT explanation

This strategy does not label liquidity from a swing that becomes obvious later. The liquidity pool is identified before the trade from a scheduled, completed cash transfer:

1. **Vulnerable side** — the final settled funding rate identifies the side whose margin is debited. Positive funding makes longs the payer; negative funding makes shorts the payer.
2. **Build-up** — extreme fit-only funding and aligned premium identify crowded inventory near the settlement boundary.
3. **Displacement** — one or two completed post-settlement five-minute bars reveal whether payer reduction is beginning or whether the market first sweeps farther and reclaims.
4. **Liquidity run** — a deferred payer flush is continuation through vulnerable inventory. A prepaid extension followed by reclaim is a completed sweep and exhaustion.
5. **Execution** — this fatal screen enters one additional full bar after confirmation to test whether the mechanism has enough residual magnitude. A survivor may later enter only on the first causal retracement into the displacement imbalance/FVG, with exact Bybit BBO and depth.
6. **Invalidation** — the settlement-derived state must remain coherent. A reclaim against the intended continuation, absent premium contraction, or loss of the first-imbalance state invalidates the corresponding setup.

The strategy is therefore explainable in familiar SMC/ICT terms—liquidity pool, displacement, liquidity run, imbalance retracement and reclaim—but every term has an exchange-native, timestamped rule.

## Frozen research stage

- Official Bybit V5 funding history, linear 5-minute kline and premium-index kline endpoints.
- BTCUSDT, ETHUSDT, SOLUSDT and XRPUSDT; one global slot.
- 2022 fit, 2023 development, 2024-2026 hard prohibited.
- 720 frozen candidate cells.
- Conservative next-open proxy with unchanged 12/18/24 bp cost replay.
- No live credentials or orders and no ranking eligibility at this stage.

See `preregistration.json` for the complete causal and survivor contract.
