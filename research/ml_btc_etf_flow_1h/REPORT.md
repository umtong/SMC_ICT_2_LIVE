# BTC ETF flow one-hour protected-structure audit

**Result:** `RES-20260730-ML-BTC-ETF-FLOW-1H-001`  
**Decision:** `RETIRED_RESEARCH_EXPOSED_SLOW_CONTINUATION_NOT_CORE_ML_FAILURE`

## Question

The parent ETF-flow route used a daily external cash-flow source with five-minute protected structure and failed. This audit changed only that semantic layer: daily ETF flow had to establish and lose protected order flow on completed one-hour bars. The full 2024-01-01 through 2026-06-30 interval had already been exposed, so this is a programization audit rather than fresh OOS evidence.

## Fixed causal account contract

- BTCUSDT only and one global pending/open slot.
- Flow dated U.S. trading day `d` becomes usable only at `00:00 UTC` on `d+1`.
- For continuation and fade separately, wait for a completed one-hour pullback against the action direction, then the first later completed one-hour resumption beyond the immediately preceding one-hour extreme.
- Activate after fixed 500 ms at the first strictly later observable canonical Bybit one-minute price.
- Protected origin is the pullback segment extreme; outer buffer is 0.25 of prior-only ATR20 on one-hour bars.
- Exit only on hard stop, completed one-hour protected-origin loss, or a later ETF-flow sign reversal. No elapsed-time or scheduled close.
- Fixed 0.5% current-NAV planned loss, 3x notional cap, actual funding, and 12/18/24-bp paths.
- Online HGBT refits on the first UTC day of each month using only labels fully resolved before that timestamp; no model trade before 40 resolved labels.

## Event funnel

- 634 source rows; 618 nonzero events.
- 1,230 action candidates; 1,225 resolved labels.
- Simple continuation selected 311 positions and completed 310.
- Exit counts: 196 stops, 85 source reversals, 29 structural exits, one ending boundary mark.
- Median trigger latency: 6.0 hours.
- Median / mean holding: 13.28 / 48.51 hours.
- Slot occupancy: 68.92%.

## Simple continuation economics

| Cost | Return | GDG/day | Trades | PF | Marked MDD | Median trade | Top-5 positive share |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 12 bp | 57.96% | 0.05014% | 310 | 1.383 | 17.98% | -0.496% | 36.68% |
| 18 bp | 39.65% | 0.03663% | 310 | 1.270 | 20.66% | -0.496% | 36.13% |
| 24 bp | 25.53% | 0.02494% | 310 | 1.175 | 22.94% | -0.496% | 35.81% |

The scale correction is real: unlike the five-minute route, the simple one-hour continuation path is positive at all three costs. It is still not a steady Core.

- 2025H1 and 2025H2 lose at every cost.
- At 24 bp only 69 of 310 completed trades win; the median is almost the full planned loss.
- All 69 completed winners exit on a later ETF-flow sign reversal. Every completed stop or structural exit loses.
- Median holding is 13.28 hours, mean holding is 48.51 hours, and the slot is occupied 68.92% of the interval.

## Exact winner deletion and full rerouting

The seven largest positive event keys were removed before rebuilding the entire one-slot path.

| Cost | Final return | GDG/day | Trades | PF | Marked MDD |
|---:|---:|---:|---:|---:|---:|
| 12 bp | 21.20% | 0.02108% | 316 | 1.141 | 17.61% |
| 18 bp | 9.85% | 0.01030% | 316 | 1.056 | 20.39% |
| 24 bp | 0.71% | 0.00078% | 316 | 0.982 | 22.74% |

At 24 bp the final marked NAV is 10,071.16, but completed-trade NAV is only 9,792.57. The last unresolved position contributes +278.59 of boundary-marked equity. Thus the completed winner-deleted path is negative and PF is below one.

## Online ML failure

At 24 bp the online HGBT loses -35.55% over 216 completed trades, PF 0.489.

Across 1,159 resolved monthly predictions:

- HGBT MAE 1.4709R versus expanding-constant 1.4344R.
- HGBT MSE 7.5906 versus constant 6.5044.
- Prediction/return Spearman -0.1163.
- Positive predictions realize mean -0.3877R, median -1.0000R, and only 17.85% are positive.
- Negative predictions are less bad on average than positive predictions.

The ML is not selecting the slow winners; it is anti-ranking them.

## Decision

The one-hour audit establishes a genuine programization lesson: a daily external inventory-flow source cannot be evaluated with five-minute protected structure. Correcting the scale reveals a slow continuation effect.

It does **not** establish the required system:

- ordinary profits still depend on long-lived source-reversal exits;
- the completed winner-deleted 24-bp account is negative;
- two consecutive half-years lose;
- the median trade is the full planned stop;
- the strategy occupies the sole slot most of the time;
- online ML is baseline-inferior;
- and this audit is research-exposed rather than fresh OOS.

The ETF-flow action family is closed under the fixed contract. No 4-hour/daily variant, threshold, model, risk, leverage, cost, or exit rescue follows. The positive simple continuation result remains a disclosed slow-flow diagnostic only and does not change ranking or deployment authority.

No credentials, paper orders, testnet orders, or live orders were used.
