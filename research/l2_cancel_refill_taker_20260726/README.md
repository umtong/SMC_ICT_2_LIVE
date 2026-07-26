# Bybit L2 cancellation–replenishment taker screen

This branch tests a new high-frequency information unit rather than retuning prior candle, trade-tape, liquidation or maker thresholds.

The engine reconstructs 100 ms Bybit top-five state, attributes best-quote removals first to contemporaneous aggressive trade consumption and treats only the residual as cancellation. It screens two causal mechanisms:

1. opposite-side liquidity withdrawal plus same-side replenishment continuation;
2. liquidity withdrawal followed by rapid same-side refill and prior-flow exhaustion reversal.

Every entry crosses the first executable Bybit quote after 100/250/500 ms. The diagnostic exits at 1/3/10 seconds are used only as a fatal economic test. A survivor cannot enter the cumulative strategy ranking until it receives a state-defined exit and a complete 2024–2026 Bybit account replay.

No credentials, paper orders, testnet orders or live orders are used.
