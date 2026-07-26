# Bybit BTC-to-SOL/XRP event-time transmission

Claim: `CLM-20260726-1015-XASSET-ALT-MICROSHOCK-001`

## Purpose

The earlier BTC-to-ETH screen failed before PnL because no development event had an economically large residual gap. This study changes the follower information unit rather than tuning that failed dependency: SOLUSDT and XRPUSDT have separate public tapes, liquidity and prior-only beta states.

The initial workflow does only two things:

1. download and SHA-identify official Bybit BTCUSDT, SOLUSDT and XRPUSDT public trades for four pre-2024 partitions;
2. count causal 1/2/5-second BTC-shock residual events under the frozen cost-aware grid.

No strategy PnL, frozen validation, 2024–2026 data, funding, bid/ask execution, leverage or orders are opened in this stage. A follower can proceed to the state-exit replay only when one frozen cell has at least 30 development events, at least 10 on each development date, and the development sample contains at least 20 prior-valid residual gaps of 24 bp or more.

## Information boundary

All beta, realized-volatility and activity estimates end before shock start. The decision occurs only after the complete leader/follower window, and any later execution replay must use an actual follower trade after 100 ms latency. Public-trade marks may be carried for features for at most two seconds; no stale interval is interpolated.
