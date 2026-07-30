# CME NDOG/NWOG current-contract decision report

**Result:** `RES-20260729-ML-CME-GAP-CURRENT-CONTRACT-001`  
**Decision:** **economic failure before official 2024; exact family retired.**

## Why the archived positive result was re-opened

The archived five-feature route returned +12.9980% in 2022 at a fixed 24 bp path, but its implementation entered at the exact next 15-minute open, used Binance as the execution proxy, and compounded trade price bps rather than sizing from account NAV and structural loss. Separate median, quarter and winner-removal gates prevented 2023 from opening.

This audit kept the same CME gap information unit, two structural destinations, five market-state features and logistic model family while correcting those program-to-strategy mismatches.

## Corrected opportunity surface

- 2021: 51 opportunities, 50 resolved labels.
- 2022: 79 opportunities, 79 resolved labels.
- 2023: 142 opportunities, 142 resolved labels.

## Corrected original policy

| stage | trades | return | geometric daily | PF | median account return | MDD | top-five positive share |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2022, 2021 model | 31 | 0.8827% | 0.002408% | 1.078 | -0.4951% | 5.82% | 94.32% |
| 2023, expanding model | 51 | -11.7207% | -0.034149% | 0.455 | -0.5000% | 11.72% | 100.00% |

The frozen 2021 model also lost 4.25% in 2023, so the failure is not caused only by expanding refit.

## Program-correction diagnostics

The old classifier learned which barrier arrived first and then maximized price-bp expected value. Two stronger NAV-aligned corrections were tested without adding market information:

1. calculate both actions' predicted account return under structural risk sizing before routing;
2. fit one pooled Ridge directly to counterfactual cost-after account returns for continuation and rebalancing.

Neither rescued the mechanism. The account-value router returned 0.18% in 2022 and -16.37% in 2023. The direct action-value Ridge returned -4.17% and -13.68%.

## Decision

The archived headline was materially inflated by proxy execution and price-bp compounding, but this is not merely a software defect with a profitable strategy hidden behind it. After the defects were corrected, 2022 was only marginally positive and every causal 2023 policy was negative. Official 2024 was not opened. No gap-size, bar-count, destination, feature, risk or leverage rescue is authorized.
