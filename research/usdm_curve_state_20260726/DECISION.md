# Decision — USD-M dated-futures curve state

Result: `RES-20260726-USDM-CURVE-001`  
Claim: `CLM-20260726-0522-USDM-CURVE-001`  
Workflow run: `30174355757`

## Verdict

Close this exact alpha family as negative evidence. All 108 preregistered candidates failed the 2022-2023 development gate, and zero candidates had positive account return at 12, 18 or 24 bps. The conditional 2024 period was never requested.

## Best observed candidate

The least-negative candidate was the 672-bar, 2.5-sigma basis-exhaustion reversal with a four-bar horizon and 2.5 ATR stop. At 18 bps it produced 22 trades, -1.0132% total return, -0.001395% geometric daily growth, 0.564 profit factor, -9.985 bps median account return and -1.6012% return after removing the largest 10% of positive trades. The same candidate was already negative at 12 bps.

Best members of all three distinct families were negative at 18 bps:

- flow-confirmed continuation: -3.5695% total return;
- perpetual catch-up: -4.4587% total return;
- exhaustion reversal: -1.0132% total return.

## Validity and source coverage

The workflow passed deterministic tests, verified every official Binance public archive against its adjacent SHA-256 CHECKSUM, reconstructed actual current- and next-quarter contracts by known expiry, used only completed bars and next-bar perpetual execution, enforced one global BTC/ETH slot, and replayed the same path at 12/18/24 bps. BTC and ETH each had 105,120 perpetual bars and about 18,500 next-quarter bars in the source panel.

The initial REST attempt was source-blocked before any market row; the recorded result comes from the corrected official-archive run. No 2024-2026 outcome and no order credential was opened.

## Research consequence

Do not spend time on adjacent threshold, holding-period, stop, leverage or execution tuning under dependency fingerprint `4d8d041bdfec18a8b1b794c3e62f328dc02289d6a9ceda45593fea9f8ceedaca`. Reconsider only if a materially different curve information source becomes available, such as deeper dated-contract order flow or a new cross-margin mechanism—not a renamed basis threshold.

The project-wide first place remains unchanged because this result is negative and unranked.
