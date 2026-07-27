# EasyCore SMC/ICT ML

**Claim:** `CLM-20260727-EASYCORE-SMC-ML-001`

This is an independent, EasyPalnam-centered system built from the immutable public-caption corpus for 쉽알남 (26), 차트브로 (62), and 지표센세 (98). Existing project alpha implementations are not inputs.

The deterministic setup chain is:

`liquidity sweep → displacement/MSS → FVG + origin order block → causal retest/rejection → opposing-liquidity delivery`

Chartbro material refines PD arrays, reference ranges, sessions, displacement, and delivery targets. Indicator Sensei material contributes volume, open-interest, account-ratio, premium/index, funding, and regime features. Those features rank transcript-faithful setups; the model cannot create an unconstrained entry.

The initial screen trains and selects thresholds, risk, leverage, and rule configuration using information available through 2023-12-31, then applies the frozen selection to 2024H1. Orders activate 500 ms after the final input becomes available. With only one-minute execution data, fills are delayed to the next complete minute; ambiguous stop/target minutes resolve against the strategy. The global portfolio permits at most one position.

The workflow depends on the canonical market-data branch until that data foundation is merged. It materializes only missing BTCUSDT 2023 and 2024H1 shards, then stores a compact result pointer and uploads full evidence.
