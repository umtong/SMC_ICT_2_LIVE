# RES-20260729-ML-PDARRAY-LIFECYCLE-001

## Decision

`TESTED_BELOW_GATE`. The corrected post-delivery PD-array lifecycle is retired without opening 2024-2026.

## Why the earlier implementation was not final

The first runner kept already consumed prior-day and confirmed-swing levels in the liquidity map and could reuse the creation-side objective after it had already been delivered. That contradicts the SMC/ICT premise that current price delivery seeks still-available liquidity. `CORR-004` assigns every level a first causal one-minute consumption time, removes it after that time, and chooses only unresolved creation-time and action-time objectives.

All earlier corrections remain active: pre-delivery mitigated arrays are excluded; same-minute target/stop contact is a stop; sizing uses the delayed entry; and the global slot does not reopen during an ambiguous exit minute.

## Corrected 2022 forward evidence

The semantic correction reduced total lifecycle events from 16,098 to 12,078 and improved the maximum logistic AUC from 0.6736 to 0.7138. Nine paths with at least 80 trades were positive at 24 bp before concentration diagnostics.

The frozen broad path selected without opening 2023 was:

- FVG only;
- creation body at least 0.25 ATR;
- interaction within 14 days after delivery;
- pooled standardized logistic, C=0.1;
- expected after-18bp utility at least 0.20%;
- 0.5% planned NAV loss and 3x notional cap.

Its 2022 account result was:

| Cost | Trades | Ending NAV | PF | MDD | Median trade |
|---|---:|---:|---:|---:|---:|
| 12 bp | 99 | 11,612.82 | 1.4720 | 6.01% | -41.07 bp |
| 18 bp | 99 | 11,045.88 | 1.3137 | 6.23% | -47.07 bp |
| 24 bp | 99 | 10,606.26 | 1.1855 | 6.42% | -53.07 bp |

This was a stable C-parameter plateau rather than a single isolated cell, so the exact path was refit on 2021-2022 and frozen before calendar 2023.

## Frozen 2023 confirmation

No threshold, feature, action, stop, target, cost, risk or leverage rule changed.

| Cost | Trades | Ending NAV | Return | PF | MDD | Median trade | Top-five positive-PnL share |
|---|---:|---:|---:|---:|---:|---:|---:|
| 12 bp | 43 | 10,126.28 | +1.263% | 1.0930 | 8.73% | -51.82 bp | 74.53% |
| 18 bp | 43 | 9,929.87 | -0.701% | 0.9481 | 9.01% | -57.82 bp | 72.92% |
| 24 bp | 43 | 9,774.94 | -2.251% | 0.8330 | 9.27% | -63.82 bp | 71.83% |

At 18 bp there were 15 positive and 28 negative trades. Exact top-10%-all-trade winner deletion with full slot rerouting ended at 9,324.39 USDT. The route therefore failed on ordinary execution cost before any risk or leverage search.

## Economic conclusion

The implementation defect was real: a consumed liquidity level must not remain a permanent draw. Fixing it materially improved 2022 and demonstrated that an SMC/ICT concept can look economically weak because the market-state map was programmed incorrectly.

The frozen next-year result nevertheless failed. Therefore the remaining problem is economic, not another justification for FVG-width tuning, extra confirmation gates, cost relaxation, or leverage rescue. Post-delivery PD-array reuse/inversion is not retained as a standalone strategy family.

## Validation

Eight focused tests pass, covering pivot availability, pre-delivery mitigation exclusion, close-through/later-retest ordering, dual-boundary loss semantics, delayed-entry sizing, global-slot timing, winner rerouting, and causal retirement of consumed prior-day/confirmed-pivot liquidity.

No credentials, paper orders, testnet orders or live orders were used.
