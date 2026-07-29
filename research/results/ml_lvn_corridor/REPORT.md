# Bybit turnover-profile low-volume corridor ML — pre-2024 decision

## Decision

`RES-20260729-ML-LVN-CORRIDOR-001` is **TESTED_BELOW_GATE**. The exact executed-turnover corridor information unit is retired. Calendar 2023 and the official 2024-01-01 through 2026-06-30 partitions were not opened.

The central failure is economic rather than predictive: the best 2022 boundary classifier reached AUC **0.7804**, but no account path that retained at least 80 completed trades remained positive after the frozen 24 bp all-in round-trip cost and exact signed Bybit funding.

## Hypothesis tested

A rolling, causal price topology was built from completed Bybit five-minute executed turnover. High-turnover nodes represented previously accepted auction zones. A contiguous low-turnover region between two nodes represented a possible low-resistance delivery corridor.

The first completed 15-minute transition from a node into a corridor created two mutually exclusive actions:

1. continue through the corridor to the far high-turnover node;
2. fail the traversal and return toward the origin node.

A pooled logistic model for BTCUSDT and ETHUSDT selected continuation, reversal, or abstention. It used only completed price, volume, OI, account-ratio, funding and cross-asset state. The current UTC day never contributed to its own topology.

## Frozen evaluation

- Source: verified canonical Bybit pandas export, manifest SHA-256 `8de81d791c9ad177c6fd2046675adda759dc7373aa1d31e01b32d9b7058e8c6d`.
- Model fit: calendar 2021 resolved events.
- Forward validation and account selection: calendar 2022.
- Topologies: 8.
- Logistic model / threshold account paths: 240.
- Fixed activation delay: 500 ms; entry at the first later one-minute open.
- One global BTC/ETH slot.
- Planned loss: 0.5% of current NAV.
- Notional cap: 3x NAV.
- Primary all-in round-trip cost: 24 bp, plus exact signed funding.
- Exit: frozen corridor boundary only; no elapsed-time liquidation.
- Same-minute target/stop ambiguity: adverse stop first.

## Results

### Nominal sparse best

- Topology: 10 bp bins, 14 prior completed days, high-density quantile 0.55, low-density fraction 0.50.
- Model: logistic `C=0.1`, expected-R threshold 1.0.
- 2022 NAV: **10,000 → 10236.22 USDT**.
- UTC calendar geometric daily growth: **0.006397%**.
- Completed trades: **10**.
- PF: **1.5726**.
- Closed-trade MDD: **2.48%**.
- Median notional return: **-37.14 bp**.
- Positive / negative trades: **2 / 8**.
- First / second half returns: **+4.96% / -2.48%**.
- Top-five positive-PnL share: **100%**.
- Exact top-10%-all-trade winner removal: **9831.24 USDT (-1.69%)**.

The positive headline is therefore a ten-trade, two-winner path and not a repeatable core engine.

### Best path retaining at least 80 trades

- Topology: 20 bp bins, 7 prior completed days, high-density quantile 0.55, low-density fraction 0.35.
- Model: logistic `C=0.1`, no expected-R cutoff.
- 2022 NAV: **10,000 → 9687.02 USDT**.
- UTC calendar geometric daily growth: **-0.008712%**.
- Completed trades: **93**.
- PF: **0.8822**.
- Closed-trade MDD: **6.68%**.
- Median notional return: **-70.99 bp**.
- Positive / negative trades: **39 / 54**.
- First / second half returns: **-3.08% / -0.05%**.
- Exact top-10%-all-trade winner removal: **8539.12 USDT (-14.61%)**.

The frontier worsened as opportunity breadth increased: the best paths with at least 100 and 150 trades ended at **9577.27** and **8600.75 USDT**, respectively.

### Nonlinear diagnostic

A HistGradientBoosting diagnostic was applied only to the sole nominally positive sparse topology. Its best path ended at **9997.20 USDT** with **21 trades**, PF **0.9968**, and median return **-69.46 bp**. It did not create a positive, breadth-preserving account path.

## Interpretation

The experiment reproduced a common failure from prior project work in a new information family: classification accuracy and economic value diverged. The model could often predict which corridor boundary would be reached first, but the predicted distance, stop geometry, costs, slot occupancy and loss distribution left no repeatable post-cost NAV growth.

The correct response is not higher risk, greater leverage, a narrower threshold or 2023 tuning. The information unit is closed and the next research family must have a different economic source.

## Project effect

- Result Registry / cumulative ranking: unchanged; this is pre-2024 below-gate evidence.
- Live-order permission: unchanged; none.
- 2023 opened: no.
- Official 2024-2026 opened: no.
- Reuse: causal turnover topology, exact first-passage engine, funding-aware action returns and global-slot accounting remain available as components, but not as an endorsed strategy.
