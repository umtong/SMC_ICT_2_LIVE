# Three-market consensus laggard catch-up Core

**Result:** `RES-20260730-THREE-MARKET-CONSENSUS-LAG-001`  
**Decision:** `RETIRED_THREE_MARKET_CONSENSUS_LAG_SUBCOST_FAILURE`

## Economic question

The earlier BTC-only leader-to-alt lag route could confuse an idiosyncratic BTC move with common price discovery. This study required two independently traded markets to complete the same normalized ten-second displacement before the third market became actionable.

BTCUSDT, SOLUSDT and XRPUSDT used completed common five-second states from registered observed 500ms public-trade bars. January-February froze per-symbol ten-second scales, the pooled upper-quartile shock threshold and the dispersion rearm boundary. An event required exactly two same-sign leaders above the threshold while the third market had the same sign but less than one-third of leader-median normalized displacement.

The laggard entered after fixed 500ms. The state target required the laggard itself to move at least half the frozen gap in the consensus direction and to close half the relative gap. Relative extension or completed leader-consensus reversal invalidated the action. The outer stop, actual funding, one global slot, 0.5% NAV risk, 3x cap and 12/18/24bp were fixed. No elapsed-time exit existed.

## Programization correction

The first evaluator allowed relative gap closure caused solely by leader retracement to be labeled a laggard catch-up. This contradicted the economic hypothesis.

The corrected target required both:

1. half-gap relative closure; and
2. an own-direction laggard move of at least half the frozen gap.

State loss retained priority when the leaders reversed. The correction changed 4,452 target labels into same-time leader-consensus reversals, but entry timestamps, exit timestamps, prices, trade selection and every account path were unchanged. The failure is therefore not an artifact of the target label.

## Event density

- raw two-leader states: **59,505**;
- accepted/rearmed events: **18,675**;
- fit / development / confirmation: **5,592 / 8,412 / 4,671**;
- resolved events: **18,669**.

The corrected exits were 3,261 laggard catch-ups, 5,294 relative extensions, 10,113 leader-consensus reversals and one outer stop.

## Gross information value

At zero execution cost, the one-slot route was broadly positive:

| Stage | Multiple | Trades | PF | MDD |
|---|---:|---:|---:|---:|
| Mar-Apr development | 2.4821x | 8,338 | 1.358 | 1.29% |
| May-Jun confirmation | 1.2543x | 4,639 | 1.270 | 2.49% |
| Continuous | 3.1132x | 12,977 | 1.318 | 2.49% |

The largest five winners supplied only **1.09%** of positive PnL. This is genuine broad short-horizon information rather than a sparse-tail effect.

However, the mean gross edge was only **0.66bp per trade**, the median was **0bp**, and the median holding time was **6 seconds**.

## Realistic-cost decision

| Cost | Development multiple | Confirmation multiple | Continuous multiple | PF |
|---:|---:|---:|---:|---:|
| 12bp | 0.00000716x | 0.01707x | 0.000000122x | 0.0426 |
| 18bp | 0.0000000614x | 0.00346x | 0.000000000212x | 0.0171 |
| 24bp | 0.00000000110x | 0.000898x | 0.000000000000991x | 0.00835 |

Deleting the five largest positive events in each forward stage before complete slot rerouting worsened every path.

The market relationship is real in a frictionless sense, but the remaining price distance is roughly an order of magnitude smaller than even the least conservative realistic cost path. More model complexity, risk or leverage cannot convert this into tradable Core alpha.

## Decision

The exact three-market consensus-lag family is retired. Do not rescue it with another return window, shock threshold, lag ratio, target fraction, state-loss definition, symbol subset, model, risk, leverage or optimistic cost assumption.

The research lesson is useful: agreement between two markets improves the sign of short-horizon laggard repricing, but public-trade data recognizes it only after almost all executable value has already been transferred. The missing Core requires either earlier information or a much larger remaining price-delivery distance.

Official 2024-2026 remained unopened. No credentials, paper orders, testnet orders or live orders were used.
