# Transcript-grounded multi-timeframe confluence day-trading route

Result: `RES-20260730-MTF-CONFLUENCE-DAYTRADE-001`  
Claim: `CLM-20260729-2345-MTF-CONFLUENCE-DAYTRADE-001` / issue #420

## Why this route was tested

The retained Korean trading examples do not trade a generic sweep/FVG checklist. They repeatedly establish a large and intermediate trend first, identify an overlapping support/resistance or genuine FVG/order-block area, wait for a lower-timeframe response, fix the structural stop, and manage at the nearest expected resistance. They also show that partial profit, breakeven protection and retaining the final structural stop are context-dependent rather than one universal rule.

`SOURCE_EVIDENCE.json` binds the exact registered caption IDs, hashes and timestamp ranges.

## Executable contract

- canonical Bybit BTCUSDT and ETHUSDT only;
- completed 1d/4h/1h structural direction;
- genuine three-candle FVG, actual engulfing-body OB, and confirmed SR-flip zones only;
- a 1h and 15m zone must genuinely overlap and both remain untouched until the same first interaction;
- a completed 5m full-body engulfing or confirmed internal-structure break must close away from the overlap;
- fixed 500ms activation and the first strictly later one-minute open;
- fixed stop beyond overlap/touch/confirmation invalidation;
- nearest prior-known and still-unconsumed 15m/1h pivot or previous-day level;
- no forced duration or scheduled close;
- exact signed funding, adverse same-minute stop-first handling, current-NAV 0.5% planned loss and 3x notional cap;
- one global pending/open slot;
- full nearest-resistance exit, 50% then breakeven, and 50% then retained structural stop are replayed separately.

## Candidate audit

| symbol | 1h zones | 15m zones | fresh overlaps | candidates |
|---|---:|---:|---:|---:|
| BTCUSDT | 13,693 | 60,491 | 4,998 | 532 |
| ETHUSDT | 12,956 | 55,272 | 4,687 | 522 |

Final candidate count: **1,054**.

## Event economics at 24bp

For the full-target route:

| year | events | mean R | median R | PF | win rate |
|---|---:|---:|---:|---:|---:|
| 2021 | 373 | -0.4217 | -0.5094 | 0.169 | 22.25% |
| 2022 | 366 | -0.4069 | -0.5214 | 0.189 | 21.58% |
| 2023 | 315 | -0.4983 | -0.6417 | 0.139 | 16.83% |

No 1h/15m zone-kind pair, response type, symbol/side combination or bias-strength group with useful breadth was positive in both 2022 and 2023.

## One-slot account results

| management | cost | final NAV | trades | PF | daily geometric growth | MDD |
|---|---:|---:|---:|---:|---:|---:|
| full nearest resistance | 12bp | 2,104.56 | 994 | 0.341 | -0.1422% | 78.95% |
| partial then breakeven | 12bp | 2,008.39 | 993 | 0.321 | -0.1465% | 79.92% |
| partial, keep structural stop | 12bp | 1,986.12 | 993 | 0.320 | -0.1475% | 80.14% |
| full nearest resistance | 24bp | 1,093.97 | 994 | 0.177 | -0.2019% | 89.06% |
| partial then breakeven | 24bp | 1,054.26 | 993 | 0.168 | -0.2052% | 89.46% |
| partial, keep structural stop | 24bp | 1,044.86 | 993 | 0.169 | -0.2061% | 89.55% |

Largest-winner removal does not change the conclusion; the ordinary path is already deeply negative.

## Programization verdict

The clean implementation repaired the earlier preliminary ambiguity around engulfing, pivot availability, target consumption, 500ms execution and management. The strategy remains negative in every year and under every management even at 12bp. The failure is therefore not explained by one exit choice or by ordinary execution-cost assumptions.

The main remaining unobservable element is the exact discretionary trend-line and volume-profile drawing visible in the videos. Treating every confirmed structure/FVG/OB/SR overlap as equivalent is demonstrably wrong, but none of the executable semantic subfamilies supplies a stable positive base from which ML or sizing can legitimately proceed.

## Decision

Retire this exact multi-timeframe overlap information unit. Do not rescue it with narrower adjacent thresholds, extra SMC nouns, lower costs, model filtering, risk or leverage. Official 2024-2026 remains unopened and the cumulative ranking is unchanged.
