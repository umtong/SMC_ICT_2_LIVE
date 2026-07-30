# Outside-business acceptance necessity audit

## Decision

`RES-20260731-OUTSIDE-BUSINESS-ACCEPTANCE-001` is **`RETIRED_PRE2024_OUTSIDE_BUSINESS_SENSOR_FAILURE`**.

The parent accepted-delivery Core was reproduced exactly: 2022 24bp `1.078475x` over 71 trades and unchanged 2023 `1.066005x` over 86 trades. The added sensor did not improve the minimum yearly growth or identify a stable causal subset.

## Logic tested

A sponsored completed-hour close beyond a frozen 96-hour external boundary may be only a late close, or it may represent actual two-sided business formed outside the old auction. The frozen sensor used the exact 60 source minutes:

- `outside_turnover_share`: turnover from minutes wholly beyond the boundary divided by all breakout-hour turnover;
- crossing-minute turnover remained in the denominator but was never credited as outside;
- `vwap_outside`: the complete-hour turnover/volume VWAP lay beyond the frozen boundary;
- `BUSINESS_ACCEPTED`: at least 50% of completed turnover was wholly outside and the VWAP was outside.

The event, action, stop, +1.5R target, state loss, costs, funding, risk and one-slot arbitration were unchanged.

## 24bp first-forward and unchanged confirmation

| Partition | Parents | 2022 trades | 2022 NAV | 2022 PF | 2022 winner-delete | 2023 trades | 2023 NAV | 2023 PF | 2023 winner-delete |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ALL | 334 | 71 | 1.078475x | 1.492 | 1.035326x | 86 | 1.066005x | 1.348 | 1.015678x |
| VWAP_OUTSIDE | 293 | 63 | 1.058954x | 1.401 | 1.016039x | 79 | 1.074967x | 1.442 | 1.035416x |
| VWAP_NOT_OUTSIDE | 41 | 14 | 1.048186x | 4.840 | 1.033643x | 12 | 0.995078x | 0.818 | 0.983673x |
| MAJORITY_OUTSIDE | 251 | 56 | 1.035897x | 1.268 | 1.001968x | 69 | 1.103841x | 1.781 | 1.063753x |
| NOT_MAJORITY_OUTSIDE | 83 | 24 | 1.063017x | 3.148 | 1.048775x | 28 | 0.993142x | 0.896 | 0.975402x |
| BUSINESS_ACCEPTED | 251 | 56 | 1.035897x | 1.268 | 1.001968x | 69 | 1.103841x | 1.781 | 1.063753x |
| NOT_BUSINESS_ACCEPTED | 83 | 24 | 1.063017x | 3.148 | 1.048775x | 28 | 0.993142x | 0.896 | 0.975402x |

`BUSINESS_ACCEPTED` was broad, not sparse: 56 trades in 2022 and 69 in 2023. It was positive and winner-resistant in both years, but it **reduced** 2022 NAV from `1.078475x` to `1.035897x`; the minimum yearly log growth fell from `0.063918` to `0.035268`. Its 2022 median was negative, while the excluded minority-outside subset was strong in 2022 and negative in 2023. No stable causal ordering existed.

Continuous candidate diagnostics also showed no useful monotonic relationship:

- outside-turnover share vs direct 24bp candidate return Spearman `-0.0192`;
- signed VWAP distance `0.0613`;
- ambiguous/crossing turnover share `-0.0356`.

## Programization checks

- Parent parity: 334 events, 101 / 105 / 128 by 2021 / 2022 / 2023.
- Every event used exactly 60 contiguous, observed one-minute rows from the exact breakout hour.
- Boundary was prior-known; turnover/volume were finite and nonnegative.
- Crossing minutes could not receive favorable outside allocation.
- Two fresh complete runs produced all 17 files byte-identically.
- No 2024+ data or official outcome was loaded.
- No ML, threshold grid, symbol/side selection, risk or leverage search was opened.

## Interpretation

The location of breakout-hour business is economically interpretable but is **not a necessary admission rule** for this Core. A majority of business outside the old range describes one accepted-auction shape; it does not identify who owns the new inventory, whether that inventory is hedged, or whether the future state will persist. Treating it as a mandatory filter discards valid 2022 Core opportunities and does not solve the 2023/official regime problem.

Retain the broader parent Core. Do not rescue this sensor with another 40/60/70% threshold, minute allocation, VWAP transform, model, product/side filter, target, stop, cost, risk or leverage change.

## Reproducibility

- Evaluator SHA-256: `9c8944836805e7b99c1bf5c18be3155a71f0005a9f001e230861bac7465e695e`
- Result SHA-256: `3369c629bed35e9db8e2b995f56972215d5a2ddf004751be41d57f4fe77f0b4c`
- Feature tape SHA-256: `16e8521e79afdb7d6ba036815e42b280975c126faad63e6c6c31ea1c20dd6dfa`
- Two-run byte identity: PASS over 17 files
