# ICT Unicorn breaker–FVG causal screen

Claim: `CLM-20260726-1539-UNICORN-001`  
Branch: `agent/r11-unicorn-model-001`

## SMC/ICT trader explanation

This is a mechanical **liquidity raid → market-structure shift → breaker → fair-value-gap overlap → first retracement** model.

For a bullish trade:

1. A swing low or previous-day low must already be confirmed and still untaken.
2. Price wicks through that sell-side liquidity and the completed bar closes back above it.
3. A later displacement bar closes through the last confirmed internal swing high.
4. The up-close candle around that internal high was the bearish order block that helped send price into the raid. Closing through it proves that order block failed; its body or full candle becomes the bullish breaker.
5. The displacement must print a classic bullish three-candle FVG that physically overlaps the breaker. That overlap is the Unicorn zone.
6. Only the **first later completed bar** that retraces into the overlap and closes above its midpoint can authorize a trade. Entry is the next exact one-minute open, not a hindsight fill inside the zone.
7. The stop is beyond the raid extreme. The target is the nearest still-untaken opposing swing high or previous-day high. The bearish model is the exact mirror.

This wording is intentionally close to how an ICT/SMC trader would narrate the chart, while every noun has an observable timestamp and invalidation rule.

## Why this is not the rejected sweep-engulf family

The earlier project screen compared ordinary engulfing, sweep-engulfing, double engulfing and sweep-plus-FVG first mitigation. It did **not** require:

- an order block identified before the raid;
- that order block to fail and convert into a breaker;
- a same-displacement FVG to overlap the breaker in price;
- a one-use first-retest lifecycle; or
- the opposing external-liquidity pool as the target.

This study therefore changes the state machine and payoff geometry rather than tuning the rejected engulf threshold.

## Historical concept provenance

A 2023 TTrades presentation describes the Unicorn model as a combination of the ICT breaker block and fair value gap, focused on the entry pattern. A July 2023 ICT breaker lesson provides the liquidity/inefficiency context. These sources define vocabulary and a falsifiable mechanism only; no displayed trade or performance claim enters the research result.

## Causal and execution contract

- Strict pivots become usable only after the right-side confirmation bars complete.
- Previous-day high/low becomes available only at the next `00:00 UTC` boundary.
- Missing source minutes break all rolling state; there is no forward fill.
- Signal occurs after the first overlap-retest bar completes; entry is the next minute open.
- Stops use adverse gaps and stop-first same-bar ordering.
- One pending/open position is allowed across BTC, ETH, SOL and XRP.
- The same paths are replayed at 12, 18 and 24 bp plus actual funding.
- Position size is the minimum of 0.5% NAV planned stop risk, 3x notional, and 0.1% of prior five-minute quote volume.
- There is no arbitrary maximum holding-time exit.

## Staging

December 2021 is warmup, 2022 is fit, and 2023 is development. The workflow cannot download 2024–2026. All 1,152 rules are frozen in `preregistration.json` before outcomes. A survivor is still not rank eligible: it requires a separately preregistered Bybit-normalized replay before opening 2024.
