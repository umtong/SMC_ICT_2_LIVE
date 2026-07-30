# Ethereum blockspace-demand acceptance Core — pre-ML decision

- Claim: `CLM-20260730-ETH-BLOCKSPACE-DEMAND-CORE-001`
- Status: `RETIRED_PRE_ML_SOURCE_DENSITY_AND_UNSTABLE_DIRECTION`
- Official 2024–2026: unopened
- Credentials/orders: none

## Source and causality

The pinned Coin Metrics ETH CSV Git blob matched `d8e4f389b37626f432a923805e5cc5fa2ad5490b`. The extracted pre-2024 table contains 1,461 complete daily rows from 2020-01-01 through 2023-12-31. `ReferenceRateUSD` is empty in the current public archive, so the screen used native-unit fee and issuance pressure and did not backfill a substitute price series.

Each source day `d` was delayed until `d+2 00:00 UTC`. Entry was the first observed Bybit one-minute open strictly after the decision plus the fixed 500 ms latency. Only canonical 2021–2023 BTCUSDT/ETHUSDT and actual funding data were used.

## Frozen state

Prior-only trailing 180-day z-scores were computed for native fees, transaction count, active addresses, fee/issuance pressure and exchange net outflow. The primary demand score was:

```text
0.50 × z(log native fees)
+ 0.25 × z(log transaction count)
+ 0.25 × z(log active addresses)
```

The high-demand boundary was the 80th percentile of scores whose delayed availability preceded 2022-01-01: `1.4294532`.

## Result

The frozen boundary produced only four high-demand decisions in 2022 and twelve in 2023. The 2022-selected 24-hour action was continuation of the prior ETH 24-hour move.

| Period | Events | 24bp mean | 24bp median | PF |
|---|---:|---:|---:|---:|
| 2022 | 4 | +91.08 bp | +60.73 bp | 2.082 |
| 2023 | 12 | -28.86 bp | -76.38 bp | 0.777 |

Continuous demand-score correlation with future ETH 24-hour return was `0.0294` in 2022 and `0.0210` in 2023. Correlation with future absolute return changed from `-0.0798` to `+0.1187`. Within-year demand quintiles did not reveal a monotonic action-value surface: highest-quintile continuation averaged `-5.56 bp` gross in 2022 and `-29.32 bp` gross in 2023.

## Decision

The route failed before ML for two independent reasons:

1. the fixed 2021 demand boundary did not create a useful post-2021 event population;
2. the continuous source state had no stable directional relation that could justify replacing the boundary with a model.

Changing the percentile, delay, trailing window, holding horizon or price-response action after observing these outcomes would be an adjacent rescue. The exact family is retired. No HGBT, risk search, official period, credential or order path was opened.
