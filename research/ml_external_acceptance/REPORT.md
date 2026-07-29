# External-range price-discovery acceptance router — decision report

**Result:** `RES-20260730-ML-EXTERNAL-ACCEPTANCE-001`  
**Decision:** retired before 2023 confirmation; ranking unchanged.  
**Claim:** `CLM-20260730-ML-EXTERNAL-ACCEPTANCE-001` / issue #441.

## Mechanism

The route did not treat an external-range break as inherently bullish, bearish, continuation or reversal. A prior-only 96-hour range was frozen, each exact level was retired after its first causal consumption, and the event was decomposed into trade-price versus index-price repricing, mark/index basis, premium, OI, account-ratio, path efficiency and BTC/ETH confirmation. It compared a first causal retest continuation, a completed reclaim reversal and flat.

## Programization audit

Four material implementation issues were separated from economics:

1. Large DataFrame joins retained multi-million-row streams; aligned canonical arrays and symbol-isolated compact states produced the identical event tape without changing science.
2. The first continuation implementation defaulted its BOS reference to the start of history when a five-minute trigger extreme was not itself a confirmed fifteen-minute pivot. The corrected anchor is the causal trigger bar.
3. A single five-minute close had been treated as higher-timeframe reacceptance. The final route requires a completed fifteen-minute close and then the fixed 500 ms delay.
4. The preliminary batch generated 2023 mechanically before the 2022 gate. The final reproducible pipeline is staged and stops after 2022 failure. All preliminary 2023 values are quarantined diagnostics.

Four focused causal/account tests pass.

## Raw economics at 24 bp

| year | action | rows | mean R | median R | positive | PF |
|---|---|---:|---:|---:|---:|---:|
| 2021 | continuation_retest | 136 | -0.7562 | -1.0000 | 8.82% | 0.148 |
| 2021 | reversal_reclaim | 304 | -0.3399 | -0.4558 | 3.29% | 0.343 |
| 2022 | continuation_retest | 151 | -0.5397 | -1.0000 | 13.25% | 0.365 |
| 2022 | reversal_reclaim | 295 | -0.0923 | -0.3937 | 7.46% | 0.802 |

The one-global-slot all-continuation account lost 39.21% in 2021 and 29.80% in 2022. The corrected all-reversal account lost 36.21% in 2021 and 7.70% in 2022. Prespecified index-supported continuation and perpetual-overshoot reversal rules did not create a broad positive region.

## ML action value

Models were fitted only on 2021 and selected only on 2022. The fixed gate required positive 18/24-bp account paths, at least 30 24-bp trades, PF above one and positive exact top-10%-winner-deletion rerouting.

- HGBT clipped-R: 2022 +1.3958% at 24 bp, 15 trades, PF 1.624; winner deletion **−2.2176%**.
- HGBT positive-return probability: 2022 +9.7450%, 9 trades, PF 4.653; winner deletion **−2.5972%**. Its 2022 AUC was 0.5727 and Brier score was worse than the constant baseline.
- Regularized logistic: 2022 **−4.4112%** at 24 bp over 199 trades; winner deletion −45.7585%.
- Constant per-action expected value authorized no trades because both training actions were negative.

**Eligible models: zero.** Calendar 2023 and official 2024-2026 are closed for this family.

## Decision

The hypothesized distinction—index-supported discovery versus leveraged perpetual chasing—did not turn a 96-hour external-range break into repeated after-cost alpha. The rare positive model paths came from a few tails rather than a broad state-dependent action advantage. No adjacent lookback, dwell, OI, premium, session, target, cost, risk or leverage rescue is justified.

No credentials, paper orders or live orders were used.
