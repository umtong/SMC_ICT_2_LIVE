# Dynamic four-asset residual research

Claim: `CLM-20260725-1738-DYNAMIC-FACTOR-001`

## Completed stages

- 11,664 preregistered fixed-horizon residual candidates on official Binance USD-M BTC/ETH/SOL/XRP 5m data for 2023.
- 5,184 preregistered rank-rotation candidates.
- 2,592 causal state-exit candidates.
- Four frozen no-weight portfolios evaluated once on 2024.
- 2025 and 2026 remained sealed.

## Best exploratory challenger

`021fbab613517a31ad98`: rank transition entry plus flow-decay state exit.

- 194 trades
- +23.16% / +16.63% / +11.18% at 12/18/24 bp
- 0.0571% net geometric daily growth
- PF 1.502
- MDD 4.63%
- top-five positive share 35.35%
- top-10%-removed return -21.93%

This candidate is a better revision-5 exploratory comparison leader than the recorded high-resistance-sweep Champion, but it is not validated, deployable or target-compliant.

## Family rejection

Every fixed-horizon, rank-rotation and state-exit candidate was negative after removing its top 10% trades under the strict registered gates. Four frozen component portfolios all lost money in 2024; the least-negative portfolio returned -10.11% at 12 bp. The dependency-fingerprint family is rejected for promotion.

## Reproduction

Use dataset `DS-BINANCE-USDM-5M-2023-2025-R1` with manifest SHA `a6f8575eccfed2129daee4596f897351d84d85ae52f061f734dc991debed3ac4`. Reconstruct `extension_bundle.tar.gz` from the hash-registered Base64 parts and run the included source files. No credentials or orders are used.
