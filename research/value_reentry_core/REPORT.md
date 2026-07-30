# Prior-day value-area reentry Core decision

**Result:** `RES-20260730-BYBIT-VALUE-REENTRY-CORE-001`  
**Decision:** `RETIRED_PRE2024_VALUE_REENTRY_CORE_FAILURE`

## Economic question

Using only the previous completed UTC day's one-minute turnover distribution, freeze a 64-bin profile, contiguous 70% value area and point of control. When price first auctions outside VAH/VAL and later closes back inside, trade the failed outside auction toward the frozen POC. This is a balance-reacceptance mechanism, not an external-high/low/FVG checklist.

## Fixed causal contract

- BTCUSDT and ETHUSDT canonical Bybit data, 2021-2023 only.
- Prior day requires all 1,440 observed one-minute rows.
- Minute turnover is allocated at turnover/volume VWAP; POC is the maximum-turnover bin.
- One first upper and lower failed-auction event per symbol/day.
- Completed five-minute reentry decision; fixed 500 ms; first strictly later one-minute execution.
- Hard stop 1 bp beyond the known excursion extreme; POC target; completed five-minute outside reacceptance is a causal state exit.
- One global BTC/ETH slot, 0.5% current-NAV planned loss, 3x cap, actual funding, 12/18/24-bp costs, no elapsed-time close.

## Coverage and opportunity density

- Complete profiles: BTC **1,095**, ETH **1,022**.
- Resolved raw events: **2,083**.
- Global-slot completed trades: **600 / 626 / 662** in 2021 / 2022 / 2023; **1,888** continuous.

The route is sufficiently frequent. Its failure is not sparse opportunity.

## Pre-2024 account economics

| Year | Cost | Return | GDG/day | Trades | PF | Median account trade | MDD | Winner-deleted return |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2021 | 12 bp | -34.29% | -0.1150% | 600 | 0.576 | -0.111% | 34.66% | -57.04% |
| 2021 | 18 bp | -43.33% | -0.1555% | 600 | 0.463 | -0.132% | 43.53% | -61.03% |
| 2021 | 24 bp | -50.00% | -0.1897% | 600 | 0.378 | -0.146% | 50.13% | -64.08% |
| 2022 | 12 bp | -38.12% | -0.1314% | 626 | 0.529 | -0.114% | 38.51% | -58.98% |
| 2022 | 18 bp | -48.41% | -0.1811% | 626 | 0.402 | -0.133% | 48.60% | -63.65% |
| 2022 | 24 bp | -55.56% | -0.2219% | 626 | 0.315 | -0.151% | 55.64% | -67.16% |
| 2023 | 12 bp | -54.20% | -0.2137% | 662 | 0.361 | -0.143% | 54.17% | -68.60% |
| 2023 | 18 bp | -64.05% | -0.2799% | 662 | 0.248 | -0.181% | 63.86% | -73.41% |
| 2023 | 24 bp | -70.21% | -0.3312% | 662 | 0.180 | -0.211% | 69.94% | -76.73% |

## Continuous 2021-2023

| Cost | Final NAV | Return | GDG/day | Trades | PF | MDD | Positive / negative |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 12 bp | 1,862.17 | -81.38% | -0.1534% | 1,888 | 0.518 | 81.51% | 435 / 1,453 |
| 18 bp | 1,051.02 | -89.49% | -0.2055% | 1,888 | 0.409 | 89.52% | 379 / 1,509 |
| 24 bp | 662.11 | -93.38% | -0.2476% | 1,888 | 0.333 | 93.38% | 351 / 1,537 |

## Why this is not a few-winner problem

The zero-cost account is weakly positive: **+12.71%**, **0.0109%/day**, PF **1.051**, 1,888 trades, top-five positive-PnL share only **8.75%**. Thus the profile narrative has a small descriptive rotation effect.

It is economically unusable:

- At 12 bp the same exact path loses **81.38%**.
- At 24 bp it loses **93.38%** and ends at **662.11 USDT**.
- Every symbol/side/year subgroup has negative average return already at 12 bp.
- Removing the largest 10% positive event keys and fully rerouting leaves the continuous 24-bp account at **289.79 USDT**, PF **0.044**.

The main leakage is repeated state failure, not one unlucky tail. Across all raw events, POC targets average **+72.38 bp** gross, but outside reacceptance exits average **-19.25 bp** and stops **-32.79 bp**. The state changes too frequently for the small POC rotation to pay taker-scale costs.

## Programization audit

The first local batch materialized post-2023 event rows because the canonical export also contains 2024-2026. No official account evaluation was opened, but this violated the intended stage boundary. The batch was quarantined. All one-minute, five-minute and funding inputs were hard-cut before `2024-01-01`, then the complete pipeline was rerun.

The corrected rerun preserved every pre-2024 economic metric. Six focused tests pass:

1. all 1,440 prior-day observations are required;
2. profile state is frozen only for the next UTC day;
3. reentry must occur on a later completed five-minute bar and execution is post-500ms;
4. same-minute target/stop ambiguity is stop-first;
5. outside reacceptance exits only after a completed state decision and later execution;
6. one global slot blocks overlaps.

Two corrected full runs produced byte-identical `RESULT.json` and semantically identical event frames.

## Decision

This exact value-area reentry route is **retired before 2024**. It is a frequent but sub-cost phenomenon, not a steady-compounding Core. ML, official 2024-2026, risk/leverage search, bin/value-area changes, passive-entry rescue and adjacent confirmation filters remain closed. Ranking and live permissions are unchanged. No credentials or orders were used.
