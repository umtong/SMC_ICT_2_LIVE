# External-liquidity raid failure BPR first-retest Core fatal screen

## Decision

`RETIRED_PRE2024_BPR_RAID_FAILURE_NOT_CORE`. This exact information unit is retired before ML, risk/leverage work, or official 2024–2026. It is not a ranking result or live authorization.

## Economic mechanism tested

A pre-known prior-day external pool is consumed by a genuine one-sided 5m FVG. A later opposing genuine FVG crosses the first auction and overlaps it, forming a two-sided balanced price range (BPR). The first later return must reject from that BPR in the opposing-displacement direction. The hypothesized payer is inventory that chased or defended the failed original raid and must unwind after opposite order flow is accepted.

BTCUSDT and ETHUSDT are only test markets. The same causal definition, volatility normalization, action set, invalidation, cost, risk, and one-slot policy was used for both.

## Programization audit before verdict

Three preliminary outputs were quarantined before interpretation:

1. The FVG ATR reference was clarified to exclude all three pattern bars (`i-2`, `i-1`, `i`).
2. A detector stored only one latent side-state per symbol, allowing an old state to suppress later UTC-day events and creating zero 2023 events. The corrected detector tracks each source date and side independently; latent states do not occupy the account slot.
3. The first daily-NAV writer kept an already-closed intraday position through UTC day-end. The corrected path marks an open position only before its exact exit and cash thereafter; minute-close and adverse-bar MDD are both reported.

The final pipeline was run twice in independent output directories and every output file was byte-identical. The validator passed 831 causal, geometry, target-life, latency, slot, NAV, and economic-boundary checks.

## Event breadth

- Total parent events: 132
- 2021: 43
- 2022: 56
- 2023: 33
- BTCUSDT: 66
- ETHUSDT: 66

The event was not absent, but it was below the frozen minimum of 60 completed one-slot trades per year.

## 24 bp account result

| Action | Trades | Positive | NAV multiple | Daily geo | PF | Median trade | Median hold | Minute MDD | Adverse-bar MDD | Top-5 positive share | Winner-deleted/rerouted |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Core to prior-day midpoint | 108 | 20 | 0.952361x | -0.004458% | 0.5744 | -0.0867% | 0.58h | 6.65% | 6.65% | 49.53% | 0.937534x |
| Expansion to opposite day boundary | 127 | 12 | 0.917023x | -0.007910% | 0.4506 | -0.1014% | 0.92h | 9.11% | 9.14% | 79.02% | 0.885129x |

### Core by year at 24 bp

| Year | Trades | Return | PF | Median trade |
|---|---:|---:|---:|---:|
| 2021 | 37 | 0.75% | 1.2207 | -0.0657% |
| 2022 | 48 | -3.64% | 0.2857 | -0.0884% |
| 2023 | 23 | -1.91% | 0.3004 | -0.0920% |

## Interpretation

The BPR narrative was economically coherent but did not create a repeatable Core. The midpoint action was weakly positive only in 2021 and materially negative in 2022 and 2023. Its median trade was negative and 88 of 108 trades lost. The farther Expansion objective worsened the distribution: only 12 of 127 one-slot trades were positive and the top five winners supplied roughly four-fifths of positive PnL.

This is not a hidden winner that needs a better model. The raw action distribution itself is broad negative after realistic cost, the yearly sign is unstable, and event density is insufficient. Adding OTE, sessions, OB labels, gap-width grids, or a classifier would repeat the project’s prior error of trying to structure an uneconomic base setup.

## Boundary

- No 2024–2026 market outcome was opened.
- No ML was trained.
- No risk, leverage, gap-width, target, stop, session, side, or symbol optimization was performed.
- No credentials or orders were used.
- This family may be reconsidered only with a materially new causal information source, not a renamed BPR/FVG threshold.
