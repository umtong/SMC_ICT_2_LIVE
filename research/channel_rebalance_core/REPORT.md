# First-causal-rebalance 96/48 channel Core audit

**Result:** `RES-20260730-BYBIT-CHANNEL-REBALANCE-CORE-001`  
**Decision:** `RETIRED_PRE2024_REBALANCE_CORE_FAILURE`

## Question

The exact all-breakout audit established that immediate post-close entry was not a steady-compounding Core. This audit held the 96-hour external boundary, 48-hour channel exit, symbols, costs, risk, leverage and global-slot contract fixed and changed only the entry semantics: wait for the first later completed five-minute pullback that touches the consumed frozen boundary and closes back in the breakout direction.

## Programization corrections

- The retest must occur after the completed breakout signal; the decision minute cannot fill itself.
- Fixed 500 ms activation is represented by the first strictly later observable one-minute open.
- A pending retest occupies the single global slot and cancels only on a predeclared state failure or replacement.
- Initial invalidation is the causal retest extreme with a 1 bp adverse buffer, capped outward by the original 2ATR disaster stop.
- A preliminary batch generated post-2023 action labels before the pre-2024 gate. Those outputs were quarantined; the final evaluator ends at `2024-01-01 00:00 UTC` and was rerun from scratch.
- Seven new semantic tests and six inherited channel tests passed. Two isolated final runs produced identical result SHA-256 `8a13968b...`.

## Event funnel

- frozen pre-2024 breakout events: **1,418**
- filled first-rebalance actions: **763**
- replaced before fill: **415**
- completed 60-minute close back inside before fill: **190**
- invalid stop after retest: **50**
- exits on structural stop / opposite channel: **734 / 29**

## Pre-2024 account economics

| Year | Cost | Return | GDG/day | Trades | PF | Realized MDD | Median trade | Winner-deleted reroute |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2021 | 13 bp | -9.32% | -0.0268% | 163 | 0.854 | 35.97% | -0.480% | -57.20% |
| 2021 | 18 bp | -15.63% | -0.0465% | 163 | 0.753 | 36.91% | -0.482% | -57.34% |
| 2021 | 24 bp | -21.20% | -0.0653% | 163 | 0.660 | 37.85% | -0.484% | -57.47% |
| 2022 | 13 bp | -13.59% | -0.0400% | 127 | 0.773 | 33.25% | -0.475% | -48.31% |
| 2022 | 18 bp | -17.63% | -0.0531% | 127 | 0.697 | 33.47% | -0.478% | -48.84% |
| 2022 | 24 bp | -21.27% | -0.0655% | 127 | 0.625 | 33.64% | -0.480% | -49.28% |
| 2023 | 13 bp | -1.18% | -0.0033% | 104 | 0.976 | 16.51% | -0.468% | -37.59% |
| 2023 | 18 bp | -6.47% | -0.0183% | 104 | 0.866 | 19.20% | -0.473% | -38.25% |
| 2023 | 24 bp | -11.11% | -0.0323% | 104 | 0.765 | 21.54% | -0.477% | -38.81% |

The route was negative in every year and at every cost. At 24 bp it returned **−21.20% / −21.27% / −11.11%** in 2021/2022/2023. The frozen gate failed, so ML, risk/leverage search and official 2024–2026 evaluation remained closed.

## What the retest changed

On the 763 pre-2024 events that produced a retest, the 24-bp event-level return improved by **27.95 bp on average** and **155.57 bp at the median** versus immediate entry on the same event subset. Nevertheless, the retest action still averaged **-32.91 bp** and had a **-50.29 bp** median after cost.

The decisive failure was structural: **96.20%** of filled retests stopped, **44.28%** of stops occurred within 15 minutes, and **70.44%** within one hour. No position survived long enough to exit on a later protected-origin loss; only 29 reached the opposite 48-hour channel exit.

## Economic lesson

Waiting for a pullback did correct part of the chase problem, but a single five-minute touch-and-close outside a consumed boundary is not protected order flow. The broad breakout distribution still lacks a repeatable Core. The positive volume-sponsored and ML-selected paths should remain classified as Expansion tails rather than being treated as steady day-trading compounding engines.

The next family must change the economic action, not add confirmation thresholds to this route. A failed-acceptance/reclaim reversal is a distinct hypothesis; another continuation retest variant would be adjacent rescue and is prohibited.

No credentials, paper orders, testnet orders or live orders were used. Ranking and live permission are unchanged.
