# YT Trinity causal ML system

Status: `DRAFT_PENDING_COMPLETE_CORPUS_DIGEST_AND_CANONICAL_DATA`

This directory implements the reusable system path for Work Claim
`CLM-20260727-0346-YT-TRINITY-ML-001`. It does not claim a market result until the
three-channel public-caption manifest is `PASS_COMPLETE`, the evidence ontology is
bound by hash, and the exact frozen survivor is replayed on canonical Bybit data.

## Economic core

The initial hypothesis space is deliberately restricted to two payoff mechanisms.

1. **Liquidity-sweep reversal**: price raids a previously knowable swing/day/week
   liquidity level and closes back through it. That bar only arms the setup. A candidate
   is emitted later, after a causal internal-structure shift with displacement and, by
   default, a same-direction FVG. The stop is beyond the raid extreme and the target is
   the next opposing external-liquidity level.
2. **Displacement break/retest continuation**: a completed-bar structure break with
   displacement/FVG only arms the setup. A candidate is emitted later, after the first
   accepted retest closes back in the break direction. The stop is beyond the retest or
   prior structure and the target is the next same-direction external-liquidity level.

Indicators, patterns, session state, volume, volatility, positioning, basis and
funding are model context. They are not independent named strategies.

## Causality

- A decision row is indexed by the canonical `available_at_ms`, not source-bar start.
- Pivots appear only after their right-side confirmation bars are complete.
- Previous day/week levels are used only after those periods close.
- Labels are first-passage outcomes with no elapsed-time strategy exit. Unresolved
  observations are censored, never relabelled as losses.
- Training rows become eligible only after all market and passive-fill outcomes are
  available. The calibration split purges base rows whose outcome overlaps the
  later calibration start.
- The model active before a scheduled update remains active until the deterministic
  training-completion lag has elapsed.

## ML policy

A pooled histogram-gradient-boosting action-value model has separate heads for:

- marketable target-before-stop probability and after-cost net-R;
- passive-order fill probability;
- passive conditional target-before-stop probability and after-cost net-R.

A passive nonfill contributes zero realized account return; it never inherits the
market-order label. Strictly later chronological tails calibrate probabilities. The
global policy compares `ABSTAIN`, `MARKETABLE`, and `PASSIVE_RETEST` by action-specific
lower-confidence expected log NAV increment after cost across BTC/ETH/SOL/XRP, and
permits at most one pending or open entry across the whole account.

## Risk and execution

Quantity starts from whole-account NAV times the selected risk fraction divided by
expected per-unit loss, including entry-to-stop distance, fees, spread, slippage,
impact and funding. Instrument quantity steps/minimums are mandatory run inputs and
must be tied to a dataset snapshot. Risk fraction, leverage and order style are
searched only after positive basic after-cost alpha; growth is never clipped at the
1% project target.

The event-tape engine implements fixed 500 ms activation, bid/ask market fills,
depth-dependent impact, resting-side queue-ahead passive fills, aggressor-direction
filters, partial fills, nonfills, funding, stop-first same-timestamp ambiguity,
structural invalidation inputs, liquidation invalidation and UTC daily NAV. Unknown
aggressor volume is not credited to a passive fill. Any unfilled entry remainder is
cancelled when the sibling position closes. Actual executable entry prices cap filled
quantity to the planned whole-account loss budget. Without an explicit reduce-only
target queue, targets cross the observable book with taker cost rather than receiving
an exact full maker fill. Coarse stops use adverse gap opens. No order or position is
closed solely because time elapsed.

## Evaluation path

1. Bind the complete transcript corpus and rule ontology by SHA-256.
2. Build causal events/labels on pre-2024 canonical data.
3. Run the 2023 sequential coarse 1-minute screen at basic risk.
4. Close the exact route if after-cost geometric growth is nonpositive; otherwise
   test conditional symbols and then risk/leverage/order style.
5. Replay the exact frozen survivor on the sub-minute event-tape lane.
6. Only an event-tape-valid survivor may open 2024H1 and enter the Result Registry.
7. Official intervals preserve one NAV path from 10,000 USDT with no half-year reset.

The 1-minute screen is explicitly provisional and cannot change the cumulative
strategy ranking.
