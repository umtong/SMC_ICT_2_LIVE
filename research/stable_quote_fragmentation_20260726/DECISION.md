# Decision — within-Binance stable-quote fragmentation

Result: `RES-20260726-STABLE-QUOTE-001`  
Claim: `CLM-20260726-0553-STABLE-QUOTE-001`  
Workflow run: `30175593398`

## Verdict

Close this exact alpha family as hard-valid negative evidence. All 108 preregistered candidates failed the 2022-2023 development gate, and zero candidates had positive account return at 12, 18 or 24 bps. The conditional 2024 period was never requested.

## Best observed candidate

The least-negative candidate was the 672-bar, 2.5-sigma non-USDT quote-share-migration state with a 1.0-sigma state exit and 2.5 ATR adverse stop. It produced 199 completed trades. Its account returns were -13.0605%, -17.1072% and -20.4966% at 12, 18 and 24 bps. At 18 bps, geometric daily growth was -0.0256984%, profit factor 0.0654, median account return -9.1296 bps, positive-trade fraction 14.07%, maximum drawdown 17.11%, and return after removing the largest 10% of positive trades -17.4347%.

The same frozen rule lost independently in both development years at 18 bps: -8.9514% over 106 trades in 2022 and -8.9577% over 93 trades in 2023.

Best members of all three economically distinct families were negative at 18 bps:

- non-USDT consensus catch-up: -20.1846% over 381 trades;
- isolated-USDT reversal: -26.2226% over 368 trades;
- non-USDT quote-share migration: -17.1072% over 199 trades.

The median candidate lost 53.6860% at 18 bps. This is not a narrow parameter miss.

## Validity and source coverage

The workflow passed nine deterministic causal and replay checks. Every Binance monthly archive was matched to its adjacent SHA-256 CHECKSUM. Non-USDT prices used exact same-timestamp completed stablecoin-to-USDT conversion bars, route changes broke rolling state, all signals used prior-only statistics, entries occurred at the next exact perpetual open, and one global BTC/ETH slot, actual funding, adverse gap stops, terminal NAV marking, identical cost paths and top-trade-removal replay were enforced.

The source panel contained 73,051 completed direct-USDT spot bars for each base, 73,056 perpetual bars for each base, 71,439 BUSD-route bars, 57,293 USDC-route bars and 14,368 FDUSD-route bars per base, for 146,102 causal base-panel rows in total. No 2024-2026 outcome and no credential or order path was opened.

## Research consequence

Do not spend time on adjacent route weights, thresholds, state-exit levels, stops, leverage, cost assumptions or execution refinements under dependency fingerprint `59828ef35a7b5a81d257cf50b1ae598db32f0becc79014ad9f391af94076fdd6`. Reconsider only with a materially different information source, such as exact-arrival order-book fragmentation or stablecoin creation/redemption flow—not another completed-bar quote-market normalization.

The project-wide first place remains unchanged because this result is negative and unranked.
