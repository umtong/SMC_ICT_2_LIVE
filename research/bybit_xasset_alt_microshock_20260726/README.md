# Bybit BTC-to-SOL/XRP event-time transmission

Claim: `CLM-20260726-1015-XASSET-ALT-MICROSHOCK-001`  
Result: `RES-20260726-XASSET-ALT-MICROSHOCK-001`

## Purpose

The earlier BTC-to-ETH screen failed before PnL because no development event had an economically large residual gap. This study changed the follower information unit rather than tuning that failed dependency: SOLUSDT and XRPUSDT have separate public tapes, liquidity and prior-only beta states.

The workflow:

1. downloaded and SHA-identified official Bybit BTCUSDT, SOLUSDT and XRPUSDT public trades for four pre-2024 partitions;
2. built causal 100 ms states and prior-only beta, realized-volatility and activity features;
3. counted completed 1/2/5-second BTC-shock residual events under the frozen cost-aware grid.

No strategy PnL, frozen validation, 2024–2026 data, funding, bid/ask execution, leverage or orders were opened. A follower could proceed only when one frozen cell had at least 30 development events, at least 10 on each development date, and the development sample contained at least 20 prior-valid residual gaps of 24 bp or more.

## Result

All twelve required public-trade archives passed HTTP, gzip, schema, timestamp monotonicity and UTC-day coverage checks.

SOLUSDT produced 22 full-filter development events: zero on 2023-05-21 and 22 on 2023-07-16. Its best frozen cell contained 21 events, all on the latter date, and the development sample had 21 raw residual gaps of at least 24 bp.

XRPUSDT produced 577 full-filter development events: zero on 2023-05-21 and 577 on 2023-07-16. Its best cell contained 335 events, all on the latter date, and the development sample had 986 raw residual gaps of at least 24 bp.

Both followers therefore failed the fixed date-breadth gate before PnL. The XRP signal was economically large in one regime but not repeatable across the two development dates.

## Decision

`RETIRE_BTC_ONLY_TO_SOL_XRP_EVENT_TIME_RESIDUAL_INFORMATION_UNIT`

Do not tune adjacent BTC-only shock, flow, activity, underreaction or gap thresholds on these four source partitions. A materially different leader state, such as a completed BTC+ETH common-information shock, may be tested without reopening this dependency.

## Information boundary

All beta, realized-volatility and activity estimates ended before shock start. The decision occurred only after the complete leader/follower window. Public-trade marks were carried for features for at most two seconds; no stale interval was interpolated. Frozen validation and all 2024–2026 periods remained sealed.
