# Volume-sponsored accepted delivery with protected-boundary lifecycle

**Result:** `RES-20260730-VOLUME-PROTECTED-BOUNDARY-BOOTSTRAP-RISK-001`  
**Decision:** provisional rank 1 by target proximity; Expansion component only; target not met; no live permission.

## Economic mechanism

A completed one-hour close consumes the prior 96 completed-hour external boundary. The breakout hour must have a log-volume z-score above the calendar-2021 upper-quartile threshold `2.2706072565`. This is interpreted as sponsored external-range acceptance, not as a generic breakout or SMC noun checklist.

The original frozen boundary is not immediately declared protected. A later completed one-hour close must first extend beyond the original signal close. Only then does a later completed reacceptance inside the frozen boundary invalidate the accepted-delivery thesis. The emergency 2ATR stop and completed opposite prior-48-hour channel remain competing structural exits. No elapsed-time or scheduled liquidation is used.

## Pre-2024 risk selection

The fixed 0.5% / 3x route was positive in 2022 and unchanged 2023, including exact positive-event deletion and one-slot rerouting. A risk grid was then evaluated only on the continuous 2022-2023 path at 24 bp. The selected risk was **7.5% planned NAV loss with a 12x cap**, maximizing the 10th-percentile daily log-growth estimate from 10,000 three-month block-bootstrap paths.

## Continuous 2024-01-01 through 2026-06-30 result

| Cost | Ending NAV | Multiple | Daily geometric | Trades | PF | Daily liquidation-value MDD | Winner-removed multiple |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 13 bp | 353,691.43 | 35.3691x | 0.391757% | 116 | 1.419 | 60.06% | 1.7553x |
| 18 bp | 267,571.05 | 26.7571x | 0.361045% | 116 | 1.391 | 60.29% | 1.4036x |
| 24 bp | 194,865.34 | 19.4865x | 0.326158% | 116 | 1.360 | 60.55% | 1.2780x |

The best path reaches **0.391757%/day**, 39.18% of the required 1%/day. The target gap is **0.608243 percentage points per day**.

## Why this is not the requested day-trading Core

At 13 bp the selected path had 32 positive and 84 negative trades; the median trade was -4.247%. The largest five and ten winners supplied 61.82% and 84.14% of positive PnL. Every selected trade held at most 48 hours lost, whereas 24 of 26 trades held beyond 120 hours won.

Thus the result is a meaningful long-duration **Expansion** alpha, not a frequent, steadily compounding day-trading Core. Risk amplification is substantial: fixed 0.5% risk produced a 24-bp 1.4328x path, while selected 7.5% risk produced 19.4865x.

## Programization and failed improvements

- Fixed a material lifecycle defect: the boundary can become protected only after later same-direction expansion.
- Corrected `0 × NaN` partial-realization accounting; 0% realization remained best.
- Retired delayed-risk completion, immediate unprotected-failure exit, both pre- and post-promotion reversal, structural-risk translation, account-state risk concentration, lower-volume expansion, 15m/4h scale transfer, SOL/XRP extension and first-retest entry.
- Found a future-information defect in a prior ML diagnostic (`promoted` used at entry); the corrected entry-only HGBT was baseline-inferior and negative after official winner deletion.

## Decision

Preserve this route as the current strongest provisional Expansion component. It is not ML-based, not target-compliant, not deployment-ready and not a substitute for the missing frequent Core engine. Do not tune official-period thresholds, channel lengths, risk or leverage to force the 1% result.

No credentials, paper orders or live orders were used.
