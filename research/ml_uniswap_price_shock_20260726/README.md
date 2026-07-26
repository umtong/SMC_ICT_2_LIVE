# Uniswap price-impact shock → ETHUSDT structural delivery

Claim: `CLM-20260726-2350-ML-UNISWAP-PRICE-SHOCK-001`

This route deliberately does **not** treat cumulative `USDC`/`WETH` fields as pool balances or signed inventory flow. PR #253 established that they are cumulative unsigned volume states. The new information unit is instead a completed DEX execution shock:

1. a completed five-minute Uniswap block-state interval has unusually large volume and price displacement;
2. the direction is only the observed completed pool-price change;
3. after a conservative 120-second availability delay, one HGBT estimates whether ETHUSDT next reaches the already-known upper or lower external-liquidity pool;
4. one cost-adjusted LONG/SHORT/FLAT rule controls one ETHUSDT slot;
5. target and stop are frozen structural liquidity pools; elapsed time never liquidates the position.

The source, model, features, chronology, action equation and execution rules are fixed before any strategy result. A positive 24-bp pre-2024 path freezes the registered risk/cap search using information through 2023-12-31 and opens 2024H1 immediately. A structurally weak 2024H1 result retires the information unit rather than triggering adjacent tuning.

No credentials or orders are used.
