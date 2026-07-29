# ICT New-York midnight-open matched daily-anchor screen

Decision: **RETIRED_STAGE1_NEGATIVE_SUBCOST_OR_NONUNIQUE**.

The study did not assume that the New-York midnight open was special. It used the same fixed `08:30–08:35 America/New_York` decision, prior-New-York-day external target, execution, funding and cost contract for four pre-known daily anchors. FVG/BPR, session-state features, ML and risk search were conditional on a positive, unique stage-1 midnight result.

## Overall economics

| anchor | events | gross mean | gross median | target rate | 12bp mean | 18bp mean | 24bp mean | 24bp PF |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| NY_0600 | 1,513 | -8.603bp | -23.096bp | 17.91% | -20.501bp | -26.501bp | -32.501bp | 0.485 |
| NY_MIDNIGHT | 1,329 | -1.110bp | -21.780bp | 26.26% | -12.828bp | -18.828bp | -24.828bp | 0.655 |
| TRUE_DAY_1800 | 1,209 | -2.999bp | -22.937bp | 30.77% | -14.708bp | -20.708bp | -26.708bp | 0.659 |
| UTC_MIDNIGHT | 1,232 | -4.608bp | -24.122bp | 30.28% | -16.217bp | -22.217bp | -28.217bp | 0.645 |

The New-York midnight anchor was the least-negative gross anchor, but it was not an edge: gross mean was already negative and the 24bp result was `-24.828bp` with PF `0.655`.

## Midnight result by year

| year | events | gross mean | 24bp mean | 24bp PF | target rate |
|---|---:|---:|---:|---:|---:|
| 2021 | 374 | -7.455bp | -30.954bp | 0.689 | 28.88% |
| 2022 | 442 | -7.322bp | -31.246bp | 0.610 | 25.57% |
| 2023 | 513 | +8.867bp | -14.832bp | 0.667 | 24.95% |

The 2023 gross improvement did not survive realistic cost and did not persist in 2021–2022.

## Matched 24bp comparisons

- versus the `18:00 ET` true-day open: `+2.574bp`, deterministic bootstrap 95% CI `[-7.528,+13.828]`, paired p=`0.646`;
- versus `00:00 UTC`: `+2.300bp`, CI `[-7.781,+12.647]`, p=`0.662`;
- versus `06:00 ET`: `+5.574bp`, CI `[-2.900,+14.692]`, p=`0.210`.

The confidence intervals all cross zero. Being less negative than an alternative anchor is not evidence of positive account alpha.

## Programization audit

Six focused tests passed:

1. New-York spring-DST day length;
2. New-York fall-DST day length;
3. completed 08:35 decision cannot fill before 08:36 under fixed 500ms latency;
4. prior-day target consumption before decision invalidates the action;
5. same-minute stop/target ambiguity is stop-first;
6. adverse gap-through stop uses the observed open.

The run produced 5,285 events, 5,283 resolved outcomes and only two unresolved/source-gap events. The failure is not explained by an obvious timing, DST, target-consumption or barrier-ordering error.

## Fixed-risk diagnostic

At 24bp, the one-global-slot New-York-midnight path used 0.5% current-NAV planned loss, a 3x notional cap and highest causal structural reward-to-risk arbitration for simultaneous BTC/ETH candidates:

- 717 trades;
- `10,000 → 2,855.76 USDT`;
- geometric daily growth `-0.114386%`;
- PF `0.565`;
- realized-NAV MDD `73.58%`.

## Decision

Stage 2 was not authorized. No FVG/BPR or session-state extension, ML policy, risk/leverage search, or official 2024–2026 evaluation was opened.

This closes only the simple directional claim:

> `price above New-York midnight open → long toward prior-day high`, and  
> `price below New-York midnight open → short toward prior-day low`.

It does not establish that the midnight open has no descriptive or discretionary contextual value. It establishes that this direct, fixed daily action is negative, sub-cost and not uniquely superior under the tested causal contract.

No credentials, paper orders or live orders were used.
