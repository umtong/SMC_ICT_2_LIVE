# Product-neutral SMC Core + Expansion single policy

## Decision

`PROVISIONAL_POSITIVE_COMPONENT_NON_ML_TARGET_NOT_MET`.

This is not a new SMC checklist and it does not claim that the four products are the thesis. The common mechanism is accepted external-liquidity delivery. BTCUSDT and ETHUSDT are test markets. Both volume and funding states are fully prior-only and pooled across products and directions.

## Programmed state lifecycle

1. A completed hourly close consumes the prior 96 completed-hour external boundary.
2. The completed breakout hour must have pooled high prior-only volume sponsorship and not be excessively crowded in the trade direction.
3. Entry activates after the project 500 ms delay and uses the first strictly later observed minute.
4. The original structural disaster stop is 2 ATR20 from the accepted boundary event.
5. At +1.5R, realize two-thirds, locking exactly +1R gross.
6. Retain one-third only when a separate later completed-hour continuation promotion is already causally available by target time.
7. The runner exits on the original stop, protected-boundary state loss or opposite 48-hour channel. There is no elapsed-time or calendar close.

## Pre-2024 fixed-risk economics

| Policy | 2022 multiple | 2023 multiple | Combined | Combined median | PF | MDD | Winner removed |
|---|---:|---:|---:|---:|---:|---:|---:|
| +1.5R Core | 1.0785x | 1.0660x | 1.1497x | 0.411% | 1.411 | 5.21% | 1.0603x |
| Core + causal runner | 1.0818x | 1.1318x | 1.2244x | 0.194% | 1.943 | 4.62% | 1.1184x |

## Continuous 2024–2026

| Policy | Cost | Multiple | Geometric/day | Trades | PF | Median | MDD | Top-5 share | Winner removed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Core | 24bp | 1.0903x | 0.00948% | 144 | 1.276 | -0.139% | 3.28% | 8.8% | 1.0209x |
| Core + causal runner | 24bp | 1.1590x | 0.01618% | 100 | 1.736 | 0.105% | 4.12% | 35.5% | 1.0345x |

Hybrid half-years at 24bp: +6.10%, +5.41%, +4.25%, -0.39%, -0.20%.

## Jackpot dependence versus steady compounding

The hybrid is materially better than the current rank-one Expansion on concentration and drawdown: it has a positive trade median, 51 winners / 49 losers, 35.5% top-five positive-PnL share, 4.12% daily MDD and 1.0345x after exact winner deletion/full rerouting. It is therefore not a one-jackpot artefact.

It is still not the target system. Forty-one of 100 trades used a runner, the final two half-years were negative, and the 24bp daily growth of 0.01618% is only about 1.6% of the 1% requirement.

## ML findings

- Target-time runner action-value ML ended at 1.1258x at 24bp versus 1.1590x for the deterministic causal-runner policy. It was rejected.
- Entry-time multi-action ML selected only 29 and 28 trades in 2022/2023, had negative medians, and failed 2022 winner deletion. It was rejected before official opening.

The surviving component is therefore deterministic and does not satisfy the project ML requirement.

## Risk and scale limits

The pre-2024 block-downside selector retained 0.5% planned loss. The impossible official-period risk/cap oracle selected 15%/40x and reached only 0.2769%/day with 74.18% MDD. No tested risk/cap path reached 1%/day.

Adding 24/48/168-hour boundaries raised frequency but made the 2023 Core negative with a negative median. It was rejected without official opening. The 96-hour family is not to be tuned further.

## Final classification

Preserve this as a reproducible low-risk Core/Expansion component. Do not promote it to the cumulative strategy ranking, call it an ML system, increase risk to chase the target, or use it as a reason to continue channel/R/threshold tuning. The missing element remains an independent frequent after-cost Core from a different economic payer.
