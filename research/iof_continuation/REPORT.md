# Scale-matched institutional order-flow continuation

**Result:** `RES-20260730-ML-IOF-CONTINUATION-001`  
**Decision:** `RETIRED_PRE2024_DETERMINISTIC_ORDERFLOW_CONTINUATION_FAILURE`

## Source-grounded mechanism

This study continues issue #398 without adding a second strategy family. It implements the recurring mechanism from the registered project sources:

1. completed 4h and 1h order flow align toward a still-unconsumed external draw;
2. a completed 15m displacement closes through a causally confirmed internal swing;
3. the most recent confirmed opposite 15m swing becomes the protected origin;
4. the first later completed 5m counter-direction pullback and subsequent directional resumption creates the executable action;
5. `NEAR` realizes at the nearest still-unconsumed 1h pool or external draw, while `HOLD` carries through an intermediate low-resistance pool toward the prior-day/confirmed-4h external draw;
6. flat remains available. No FVG, OB, session, OTE or reward-to-risk grid is used.

The account uses canonical Bybit BTCUSDT/ETHUSDT data, fixed 500ms activation, first strictly later observed 1m execution, actual signed funding, 0.5% current-NAV planned loss, 3x cap, 12/18/24bp costs, one global pending/open slot and no elapsed-time or stage-boundary strategy close.

## Programization findings

- Every 4h/1h/15m pivot becomes usable only after two fully completed right-side bars.
- The 15m displacement is accepted only when the completed 1h and 4h order-flow states already agree.
- A 5m pullback bar cannot also be its own resumption trigger; the resumption must be a later completed bar.
- Pending setups occupy the sole global slot until fill, causal state cancellation or replacement by a later same-symbol displacement.
- Levels must be available and still unconsumed immediately before executable entry.
- Entry and state-loss exits activate at decision availability plus 500ms and execute at the first strictly later observed 1m open.
- Same-minute stop/target ambiguity is stop-first; a gap through the stop executes at the observed adverse open.
- Open boundary exposure is marked, not strategy-closed.

## Event funnel

| Symbol | 15m aligned displacements | Filled first-pullback candidates | Causal cancellations | No live external target |
|---|---:|---:|---:|---:|
| BTCUSDT | 935 | 529 | 376 | 30 |
| ETHUSDT | 887 | 514 | 344 | 29 |

The filled candidate population is broad: 1,043 events before global-slot arbitration across 2021–2023.

## Raw action economics

At 24bp, before global-slot competition:

| Action | 2021 events | Mean | Median | PF | 2022 events | Mean | Median | PF | 2023 events | Mean | Median | PF |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| NEAR | 418 | -0.36% | +0.05% | 0.668 | 342 | -0.25% | +0.08% | 0.738 | 283 | -0.34% | -0.13% | 0.412 |
| HOLD | 418 | -0.48% | -0.95% | 0.666 | 342 | -0.22% | -0.71% | 0.803 | 283 | -0.44% | -0.56% | 0.390 |

`HOLD` was only approximately flat before cost in 2022; it was negative at zero cost in 2021 and 2023. `NEAR` had a positive median in 2021–2022 but a negative mean and PF below one, so frequent small targets were outweighed by structural losses.

## One-global-slot account

| Year | Action | Cost | Trades | End multiple | PF | Median NAV return | MDD |
|---:|---|---:|---:|---:|---:|---:|---:|
| 2021 | NEAR | 24bp | 255 | 0.848540x | 0.671 | +0.017% | 16.62% |
| 2021 | HOLD | 24bp | 218 | 0.849237x | 0.718 | -0.480% | 16.58% |
| 2022 | NEAR | 24bp | 225 | 0.828424x | 0.618 | +0.015% | 17.50% |
| 2022 | HOLD | 24bp | 204 | 0.858348x | 0.724 | -0.491% | 14.37% |
| 2023 | NEAR | 24bp | 177 | 0.781991x | 0.403 | -0.089% | 22.48% |
| 2023 | HOLD | 24bp | 164 | 0.738822x | 0.386 | -0.500% | 26.12% |

Both actions also lost at 12bp and 18bp in every year. Exact deletion of the largest 10% positive event keys followed by full pending/open-slot rerouting made every 24bp path more negative; for 2022, `NEAR` fell to 0.750413x and `HOLD` to 0.774555x.

## Why ML did not open

The contract requires raw deterministic headroom before ML. That condition failed:

- neither action is cost-positive in 2021, 2022 or 2023;
- the result is not a sparse-tail illusion—the event population and account breadth are large;
- the first-pullback programization correction did not recover a stable edge;
- adding FVG/OB/session gates or an ML filter would be another attempt to rescue a negative base distribution.

## Decision

The exact scale-matched higher-timeframe order flow → 15m displacement → first causal 5m pullback continuation information unit is retired.

The result does not say that every discretionary trend continuation is invalid. It says that this causal, reusable and sufficiently broad completed-bar representation does not contain enough information to cover realistic cost. The missing distinction remains whether the pullback is locally absorbed and sponsored rather than merely geometrically valid; the available broad cross-venue taker-flow sensor was independently tested and did not supply that distinction.

Calendar 2024–2026, ML, risk/leverage search and adjacent FVG/OB/session rescue remain unopened. No credentials or orders were used.
