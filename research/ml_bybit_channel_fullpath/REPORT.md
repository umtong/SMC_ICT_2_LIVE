# Exact Bybit channel-acceptance ML full-path result

**Result:** `RES-20260730-BYBIT-DONCHIAN-ML-FULLPATH-001`  
**Decision:** provisional new cumulative rank 1 by target proximity; target not met and no live permission.

## Fixed system

- Bybit USDT-linear BTCUSDT and ETHUSDT; one global slot.
- A completed 60-minute close outside the previous 96 completed hours creates a pre-existing acceptance-continuation candidate.
- Entry activates after the fixed 500 ms delay and uses the first later observable one-minute open.
- Exit is the 2ATR structural disaster stop or a completed close through the opposite 48-hour channel. No elapsed-time or scheduled liquidation is used.
- One HGBT mean/35th-percentile blend estimates direct 13 bp after-cost action value. The policy family and zero threshold were selected on 2022 after a 2021 fit, then survived frozen 2023 confirmation.
- The model refits at each UTC calendar-year boundary using only candidates fully resolved before that boundary.
- Account risk was selected with only 2022-2023 evidence: 5% planned NAV loss and a 12x notional cap. Actual used leverage peaked at 7.41x.
- Actual signed Bybit funding and 13/18/24 bp execution paths are included.

## Continuous 2024-01-01 through 2026-06-30 result

| Cost | Ending NAV | Multiple | Daily geometric | Trades | PF | Daily liquidation-value MDD |
|---:|---:|---:|---:|---:|---:|---:|
| 13 bp | 26,784.95 | 2.6785x | 0.108091% | 80 | 1.214 | 57.59% |
| 18 bp | 23,106.39 | 2.3106x | 0.091876% | 80 | 1.184 | 57.97% |
| 24 bp | 19,603.32 | 1.9603x | 0.073834% | 80 | 1.150 | 58.60% |

At 13 bp the route reaches **0.108091%/day**, 2.79x the stale shared first place, but only 10.81% of the 1%/day completion requirement.

## Half-year path at 13 bp

| Period | Start NAV | End NAV | Return | Daily geometric | Entry count | PF on exits |
|---|---:|---:|---:|---:|---:|---:|
| 2024H1 | 10,000.00 | 17,862.87 | 78.63% | 0.3193% | 17 | 1.823 |
| 2024H2 | 17,862.87 | 19,993.54 | 11.93% | 0.0613% | 14 | 1.213 |
| 2025H1 | 19,993.54 | 20,911.78 | 4.59% | 0.0248% | 14 | 1.129 |
| 2025H2 | 20,911.78 | 37,596.81 | 79.79% | 0.3193% | 22 | 1.486 |
| 2026H1 | 37,596.81 | 26,784.95 | -28.76% | -0.1872% | 13 | 0.382 |

The path is positive in 2024H1, 2024H2, 2025H1 and 2025H2, then loses 28.76% in 2026H1. This is a real regime failure, not a calculation or liquidation event.

## Concentration and survival

- 13 bp top-five positive-PnL share: **68.98%**.
- Exact top-10%-winner deletion before full slot rerouting: **13,270.82 USDT**, **0.031034%/day**, 81 trades, PF 1.064.
- Ordinary daily liquidation-value MDD: **57.59%**; winner-removed MDD: **63.85%**.
- No forced liquidation occurred in any 13/18/24 bp path.

## Decision

This result should replace the stale retired Donchian/HGBT proxy as provisional rank 1 because it is an exact Bybit, actual-funding, continuous 912-day path and has materially higher after-cost growth. It is not target-compliant or deployment-ready.

The remaining defects are economic rather than basic execution defects:

- the route has a negative median trade and relies on infrequent accepted trends;
- 2026H1 shows that annual action-value refitting does not prevent an extended false-breakout regime;
- 5% planned risk creates more than 57% daily liquidation-value drawdown;
- even after winner removal the growth is only 0.0310%/day, far from the objective.

Do not rescue the route with more channel lookbacks, leverage, or 2026-aware thresholds. The next work should seek an independent positive Core engine or a pre-2024-defined regime state that improves the 2026-type failure without sacrificing the large accepted-delivery Expansion trades.
