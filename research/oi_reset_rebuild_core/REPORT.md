# Leveraged-inventory reset-to-rebuild intraday Core

- Claim: `CLM-20260730-OI-RESET-REBUILD-CORE-001`
- Result: `RES-20260730-OI-RESET-REBUILD-CORE-001`
- Status: `RETIRED_PRE2024_DETERMINISTIC_ECONOMIC_FAILURE`
- Hard validity: `PASS_CAUSAL_CANONICAL_PRE2024_DETERMINISTIC_SCREEN`
- Official 2024-2026: unopened
- Credentials/orders: none

## Economic question

A completed 15-minute price/turnover shock must first reduce open interest, retain at least half of its displacement, and then causally rebuild at least half of the OI loss within four completed bars. This is a sequential inventory transition, not a one-bar price/OI classifier or an SMC shape.

## Candidate inventory

- `PRIMARY_REBUILD`: 462 candidates; 2022=157, 2023=230; mean 24bp event return=-0.281407%.
- `CONTROL_NO_RESET`: 610 candidates; 2022=236, 2023=206; mean 24bp event return=-0.236580%.
- `CONTROL_NO_REBUILD`: 487 candidates; 2022=169, 2023=233; mean 24bp event return=0.040868%.

## Fixed-small-risk account results

### PRIMARY_REBUILD

| Period | Cost | Final NAV | g/day | Trades | PF | MDD | Median hold | Top-5 share |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2021 | 12bp | 9031.84 | -0.027894% | 53 | 0.424 | 10.05% | 3.43h | 63.25% |
| 2021 | 18bp | 8994.87 | -0.029018% | 53 | 0.402 | 10.35% | 3.43h | 64.02% |
| 2021 | 24bp | 8960.15 | -0.030077% | 53 | 0.381 | 10.63% | 3.43h | 64.84% |
| 2022 | 12bp | 9110.24 | -0.025527% | 127 | 0.764 | 15.85% | 2.27h | 34.21% |
| 2022 | 18bp | 8955.23 | -0.030227% | 127 | 0.720 | 16.68% | 2.27h | 34.68% |
| 2022 | 24bp | 8813.32 | -0.034602% | 127 | 0.679 | 17.44% | 2.27h | 35.18% |
| 2023 | 12bp | 9447.47 | -0.015571% | 153 | 0.875 | 12.08% | 4.32h | 30.81% |
| 2023 | 18bp | 9102.89 | -0.025748% | 153 | 0.795 | 13.15% | 4.32h | 31.48% |
| 2023 | 24bp | 8808.02 | -0.034767% | 153 | 0.723 | 14.99% | 4.32h | 32.23% |
| CONTINUOUS_2021_2023 | 12bp | 7773.58 | -0.022998% | 333 | 0.745 | 24.08% | 3.27h | 17.66% |
| CONTINUOUS_2021_2023 | 18bp | 7332.49 | -0.028331% | 333 | 0.688 | 28.14% | 3.27h | 18.01% |
| CONTINUOUS_2021_2023 | 24bp | 6955.58 | -0.033149% | 333 | 0.637 | 31.62% | 3.27h | 18.41% |

- 2022 exact top-five winner deletion and full reroute, 24bp: NAV 7909.12, 127 completed trades, PF 0.41989031484119077.
- 2023 exact top-five winner deletion and full reroute, 24bp: NAV 7950.76, 152 completed trades, PF 0.5154034882192604.

### CONTROL_NO_RESET

| Period | Cost | Final NAV | g/day | Trades | PF | MDD | Median hold | Top-5 share |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2021 | 12bp | 9395.05 | -0.017095% | 113 | 0.782 | 9.06% | 4.93h | 25.63% |
| 2021 | 18bp | 9286.70 | -0.020273% | 113 | 0.743 | 9.52% | 4.93h | 25.91% |
| 2021 | 24bp | 9185.26 | -0.023281% | 113 | 0.706 | 9.95% | 4.93h | 26.20% |
| 2022 | 12bp | 9727.85 | -0.007559% | 165 | 0.934 | 9.04% | 3.38h | 26.51% |
| 2022 | 18bp | 9500.90 | -0.014026% | 165 | 0.878 | 9.74% | 3.38h | 26.95% |
| 2022 | 24bp | 9294.36 | -0.020047% | 165 | 0.826 | 10.39% | 3.38h | 27.41% |
| 2023 | 12bp | 10344.33 | 0.009275% | 126 | 1.092 | 11.49% | 3.16h | 44.49% |
| 2023 | 18bp | 9993.52 | -0.000178% | 126 | 0.998 | 13.16% | 3.16h | 44.79% |
| 2023 | 24bp | 9695.24 | -0.008479% | 126 | 0.917 | 14.60% | 3.16h | 45.17% |
| CONTINUOUS_2021_2023 | 12bp | 9454.07 | -0.005127% | 404 | 0.946 | 15.27% | 3.64h | 18.91% |
| CONTINUOUS_2021_2023 | 18bp | 8817.48 | -0.011492% | 404 | 0.880 | 19.93% | 3.64h | 18.59% |
| CONTINUOUS_2021_2023 | 24bp | 8276.93 | -0.017269% | 404 | 0.821 | 23.96% | 3.64h | 18.34% |

- 2022 exact top-five winner deletion and full reroute, 24bp: NAV 8467.06, 163 completed trades, PF 0.6121909676644508.
- 2023 exact top-five winner deletion and full reroute, 24bp: NAV 8072.14, 136 completed trades, PF 0.5080216909736058.

### CONTROL_NO_REBUILD

| Period | Cost | Final NAV | g/day | Trades | PF | MDD | Median hold | Top-5 share |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2021 | 12bp | 9341.64 | -0.018657% | 57 | 0.563 | 6.70% | 6.55h | 44.61% |
| 2021 | 18bp | 9294.27 | -0.020049% | 57 | 0.532 | 7.16% | 6.55h | 44.90% |
| 2021 | 24bp | 9249.98 | -0.021358% | 57 | 0.504 | 7.58% | 6.55h | 45.36% |
| 2022 | 12bp | 11055.87 | 0.027504% | 111 | 1.383 | 7.29% | 6.22h | 41.46% |
| 2022 | 18bp | 10809.16 | 0.021320% | 111 | 1.296 | 7.83% | 6.22h | 40.67% |
| 2022 | 24bp | 10592.47 | 0.015771% | 111 | 1.219 | 8.34% | 6.22h | 40.02% |
| 2023 | 12bp | 10142.82 | 0.003885% | 108 | 1.051 | 6.94% | 5.12h | 29.55% |
| 2023 | 18bp | 9920.83 | -0.002178% | 108 | 0.971 | 8.11% | 5.12h | 30.11% |
| 2023 | 24bp | 9724.88 | -0.007643% | 108 | 0.900 | 9.16% | 5.12h | 30.65% |
| CONTINUOUS_2021_2023 | 12bp | 10475.50 | 0.004242% | 276 | 1.068 | 10.36% | 5.84h | 20.31% |
| CONTINUOUS_2021_2023 | 18bp | 9966.79 | -0.000304% | 276 | 0.995 | 12.19% | 5.84h | 20.26% |
| CONTINUOUS_2021_2023 | 24bp | 9528.45 | -0.004411% | 276 | 0.930 | 13.84% | 5.84h | 20.24% |

- 2022 exact top-five winner deletion and full reroute, 24bp: NAV 9457.09, 112 completed trades, PF 0.7947616487023543.
- 2023 exact top-five winner deletion and full reroute, 24bp: NAV 9087.05, 108 completed trades, PF 0.6678181703681961.

## Decision

The deterministic primary state did not remain positive, non-sparse and winner-resistant in both 2022 and 2023 at 24bp. ML, risk/leverage search and official 2024-2026 therefore remain closed. The exact reset-to-rebuild information unit is retired without adjacent rescue.

The result does not change the cumulative ranking or live authority.

## Programization and independent reproduction

Five pre-publication programization corrections were applied: exact calendar rather than retained-row normalization; contiguous 15-minute OI returns; exclusion of missing OI from the no-reset control; nested turnover-surprise readiness; and annual rather than global top-five deletion in the continuous stress. The final source passes 11 semantic/account tests.

The authoritative and independent repeat runs have `91` common scientific output files and zero byte mismatches. Causal invariants checked `1559` event rows and `2026` trade rows, with zero timing, geometry, nonfinite-score, cost or prohibited-time-exit violations.

The final 24bp primary inventory has a median hold of `3.32` hours and useful frequency, but its event-level mean gross price return is `-0.0454%` before cost. Fixed-horizon diagnostics also remain below the 24bp cost at every 2022 horizon and all but the 2023 24-hour mean, whose median remains negative. The failure is therefore not explained by an overlong target, a slow state exit, or insufficient leverage.

Final authority hashes:

- CONTRACT: `7bd712db899b4c140c40f62439ed0c8a9aa7a5b5391d6a2c4de5da779c247620`
- RESULT: `15cb1d781e8a111e10b4266a9360b6fd5483fa9faddebbdb9aabfc5e235b786c`
- runner: `ee1570210c799d3853d87cc63aa308bb6e406c0fa7e7165694a510254cebbda1`

No known programization defect remains that could plausibly reverse the economic decision.
