# Bybit BTC+ETH common-factor microshock screen

Claim: `CLM-20260726-1023-COMMON-FACTOR-MICROSHOCK-001`  
Result: `RES-20260726-COMMON-FACTOR-MICROSHOCK-001`

## Distinct hypothesis

The predecessor used BTC alone as the event-time leader. This study required BTC and ETH to move in the same direction, combined their prior-volatility-normalized returns and aggressive-flow state, and estimated each SOL/XRP response with a prior-only two-leader ridge regression. It did not retune the rejected BTC-only dependency.

## Causal screen

Four SHA-fixed pre-2024 public-trade dates were used. All regression coefficients, scales and activity baselines ended before shock start. Decisions used completed 1/2/5-second windows. Each frozen parameter cell applied a five-second event cooldown so overlapping 100 ms rows from one physical impulse could not masquerade as independent events.

No PnL, frozen validation, 2024–2026 data, funding, bid/ask execution, leverage or orders were opened.

## Result

SOLUSDT had twelve development full-filter rows, all on 2023-07-16. After independence thinning, the best cell had one event. Only three prior-valid development rows had a residual gap of at least 24 bp.

XRPUSDT had five development full-filter rows, all on 2023-07-16. The best cell had two independent events and no prior-valid development row had a residual gap of at least 24 bp.

The 2023-05-21 development partition had zero prior-valid common-factor events for either follower. Both followers failed the fatal event-availability gate before PnL.

## Decision

`RETIRE_TRADE_PRINT_COMMON_FACTOR_RESIDUAL_INFORMATION_UNIT`

Do not tune adjacent trade-print common-shock, leader-balance, flow, activity, underreaction or residual-gap thresholds. The next information unit must expose executable quotes or depth rather than infer an actionable lag from asynchronous last trades.
