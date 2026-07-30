# Bybit failed-acceptance reclaim Core

**Result:** `RES-20260730-BYBIT-FAILED-ACCEPTANCE-RECLAIM-CORE-001`  
**Decision:** `RETIRED_FAILED_ACCEPTANCE_RECLAIM_BASE_FAILURE`  
**Official 2024–2026:** unopened  
**Ranking/live authority:** unchanged / none

## Economic mechanism

The broad 96/48 breakout and its first-rebalance continuation entry had already failed as Core. This study tested the economically opposite state rather than adding another continuation filter.

A completed one-hour close first consumed a prior-known 96-hour external boundary. No reversal was allowed at that point. The event became eligible only after the first later completed one-hour close returned inside the **same frozen boundary**, indicating that outside price acceptance had failed.

The reversal represented trapped initiative and following inventory unwinding toward either:

1. the frozen original 96-hour midpoint, or
2. the frozen opposite 96-hour external boundary.

The stop was one basis point beyond the maximum excursion observed from the breakout signal through the reclaim. A later completed close outside the failed boundary invalidated the rejection thesis. No elapsed-time or scheduled liquidation was used.

## Frozen execution and account contract

- canonical Bybit BTCUSDT and ETHUSDT;
- one non-overlapping excursion episode per symbol;
- reclaim must occur before the frozen opposite boundary is consumed;
- decision close plus fixed 500ms, then first strictly later observable one-minute open;
- adverse same-minute stop priority and adverse gap-stop execution;
- actual signed funding;
- one global slot;
- fixed 0.5% current-NAV planned loss and 3x cap;
- 13/18/24bp;
- 2021 descriptive, 2022 forward development, unchanged 2023 confirmation;
- evaluation boundaries mark open positions rather than strategy-closing them.

## Event funnel

The pre-2024 run produced 134 unique failed-acceptance events and 267 valid action rows:

| Year | Midpoint | Opposite boundary |
|---:|---:|---:|
| 2021 | 47 | 47 |
| 2022 | 49 | 49 |
| 2023 | 37 | 38 |

This is already too sparse to be the missing frequent day-trading Core, but it was still economically evaluated because the action could in principle carry a large repeatable edge.

## Midpoint action

### 24bp account results

| Period | NAV | Completed trades | PF | Median trade | Top-five share | Winner-deleted NAV |
|---|---:|---:|---:|---:|---:|---:|
| 2021 | 9,496.89 | 45 | 0.399 | -0.142% | 91.40% | 9,173.22 |
| 2022 | 10,081.88 | 46 | 1.133 | -0.102% | 75.28% | 9,574.65 |
| 2023 | 9,983.60 | 37 | 0.967 | -0.082% | 84.66% | 9,617.56 |
| continuous 2022–2023 | 10,065.35 | 83 | 1.058 | -0.102% | 50.64% | 9,208.47 |

The unchanged action was only weakly positive in 2022, slightly negative in 2023 and strongly negative in 2021. Its event-level 24bp mean changed from `-58.80bp` to `+10.09bp` to `-20.85bp` across those years.

The 2022 account did not represent a broad base engine. Removing the five largest positive event keys before a complete one-slot reroute changed NAV from `10,081.88` to `9,574.65`. The same exact procedure was negative in 2023 and 2021 as well.

## Opposite-boundary action

The ambitious external-to-external reversal was negative throughout:

| Period | 24bp NAV | Completed trades | PF | Winner-deleted NAV |
|---|---:|---:|---:|---:|
| 2021 | 9,724.34 | 42 | 0.644 | 9,122.29 |
| 2022 | 9,543.20 | 40 | 0.386 | 9,220.75 |
| 2023 | 9,661.35 | 34 | 0.433 | 9,427.16 |
| continuous 2022–2023 | 9,220.02 | 74 | 0.406 | 8,734.60 |

At the event level its 24bp mean was negative in every year. Most exits were later reacceptance outside the boundary rather than target delivery, and the few winners carried essentially all positive PnL.

## Programization audit

Six focused tests passed:

1. completed decisions cannot enter before the first strictly later minute;
2. funding signs match the held side;
3. same-minute stop and target ambiguity resolves to the stop;
4. reacceptance state loss executes at the next observable minute;
5. the real event ledger has unique event/action keys, valid direction geometry and no post-2023 decisions;
6. the frozen base failure prevents ML and official-period opening.

Two complete local runs produced byte-identical `RESULT.json` and event ledgers:

- result SHA-256 `6f4d8aa4e5c075ad98d938fa6b40610b7d22918b715d30e9e8a99564b6df31b9`;
- event-ledger SHA-256 `b7df8e615612ffd9f1f982377210abe15347bc94e9fa6efe93882ca97bb6e7b7`.

No remaining timing, target-consumption, stop geometry, state-loss or slot defect explains the result.

## Decision

Waiting for actual reclaim was more logical than immediately fading every breakout and improved the 2022 midpoint distribution. It still did not create the requested Core:

- low event density;
- negative median trades;
- inconsistent yearly sign;
- exact winner-deletion failure in every year;
- opposite-boundary delivery negative throughout.

This is an economic failure after causal programization, not a candidate for ML, risk or leverage rescue. Do not change the 96-hour scale, reclaim definition, targets, stop buffer, latency, costs, risk or leverage after observing the outcome. Official 2024–2026 remains unopened.

The protected-boundary accepted-delivery route remains the provisional rank-one **Expansion**. A materially different, frequent and winner-resistant ML Core is still missing.
