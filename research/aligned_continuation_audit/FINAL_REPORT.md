# Aligned-continuation 33034b current-contract decision

**Result:** `RES-20260730-ALIGNED-CONTINUATION-CURRENT-CONTRACT-001`  
**Decision:** `RETIRED_OFFICIAL_2024H1_ECONOMIC_FAILURE`

## What was repaired

The exact registered source was recovered and reproduced. The audit then removed the prohibited 720-minute liquidation, corrected the 500 ms activation boundary, transported stop geometry to Bybit by signal-relative ratios, implemented causal protected-order-flow loss, and corrected winner deletion so a removed simultaneous candidate reroutes to the next eligible candidate.

The first official replay also exposed two initialization defects: it ignored pre-2024 universe selection and trained only on 2022. The corrected restart selected BTCUSDT+SOLUSDT from 2022/2023 only and refit the already-selected class-balanced logistic policy on all labels resolved before 2024.

## Pre-2024 evidence for the frozen BTC/SOL ML policy

- 2022 forward, 24 bp: **+2.6692%**, 19 trades, PF **1.936**; exact winner reroute **+2.4279%**.
- Frozen 2023, 24 bp: **+7.2748%**, 47 trades, PF **1.756**; exact winner reroute **+0.1421%**.

## Restarted official 2024H1

| cost | return | GDG/day | trades | PF | marked MDD | median R | top-5 positive share |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 15 bp | -1.4964% | -0.008284% | 25 | 0.784 | 2.743% | -0.797 | 91.67% |
| 18 bp | -2.5342% | -0.014102% | 25 | 0.633 | 2.756% | -0.804 | 90.49% |
| 24 bp | -2.8242% | -0.015740% | 25 | 0.593 | 2.941% | -0.816 | 91.61% |

The unfiltered event mechanism was only +0.3549% at 15 bp and negative at 18/24 bp. The ML policy did not preserve its pre-2024 ordering skill. Risk and leverage optimization therefore remain closed. H2 was not opened, the ranking is unchanged, and the historical `life720` rank pointer is not current-contract eligible.

## Economic lesson

The original apparent breadth was partly real, but it depended on coarse completed-bar state and a prohibited elapsed-time lifecycle. Correcting the lifecycle retained pre-2024 alpha, yet the information unit did not persist into 2024. Further threshold, subset, risk, leverage, or target rescue under the same dependency is not justified. The next route changes the information source to microbar-level liquidity consumption and absorption rather than another 5m/15m checklist.

No credentials, paper orders, testnet orders, or live orders were used.
