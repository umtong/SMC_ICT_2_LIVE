# 48h/24h volume-sponsored acceptance-loss lifecycle audit

**Result:** `RES-20260730-48H24H-SPONSORED-LIFECYCLE-001`  
**Status:** `RETIRED_PRE2024_LIFECYCLE_FAILURE`  
**Official 2024-2026:** unopened  
**Orders:** none

## Question

The local provisional 48h breakout / opposite-24h-channel route was profitable at fixed small risk, but its short-duration trades lost in aggregate and its value came from multi-day accepted-delivery tails. This audit kept the parent event, sponsorship boundary, symbol-sides, executable entry, stop, funding, costs, risk, cap and one-global-slot contract unchanged. It tested whether a causal loss-of-acceptance exit could remove losing short holds without an elapsed-time close.

## Frozen parent

- completed one-hour close beyond the prior 48 completed hours;
- breakout-hour log-turnover z-score versus the prior 168 completed hours above `2.2706072565238586`;
- BTC long, ETH long and ETH short only;
- first complete one-minute open strictly after decision plus 500 ms;
- 2 ATR20 disaster stop;
- opposite prior-24h channel close as the parent structural exit;
- actual signed funding, adverse ambiguity, 0.5% NAV planned loss, 3x cap and 24 bp primary cost.

## Programization audit

The corrected evaluator gives the same parent official diagnostic as the legacy exit-minute ordering:

- NAV multiple: `1.35253186x`;
- daily geometric growth: `0.033117%`;
- completed trades: `143`;
- UTC daily liquidation-value MDD: `8.0855%`;
- median net trade return: `-1.4033%`;
- median hold: `36.02 h`.

The route's positive headline is therefore not explained by the tested exit-minute stop-ordering implementation detail.

## Pre-2024 result at 24 bp

| Route | 2022 NAV | 2022 trades | Median trade | H1 | H2 | Top-5 deleted/rerouted NAV | 2023 NAV | 2023 H2 | 2023 deleted/rerouted NAV |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| first reclaim | 1.26698x | 55 | -1.0737% | +18.95% | +6.51% | 1.15466x | 1.22657x | -1.74% | 1.00752x |
| two reclaims | 1.27206x | 54 | -1.3272% | +20.60% | +5.48% | 1.19567x | 1.22413x | -0.44% | 1.02363x |
| reclaim then body midpoint loss | 1.31567x | 51 | -1.1300% | +22.48% | +7.42% | 1.23666x | 1.19948x | -2.43% | 1.01539x |
| parent opposite-24h channel | 1.30311x | 51 | -1.3310% | +21.91% | +6.89% | 1.22486x | 1.19938x | -1.20% | 1.03355x |

Every route failed the frozen 2022 selection contract. Each had fewer than 60 completed trades and a negative median trade. More importantly, every unchanged 2023 route had a negative second half; winner deletion and full rerouting made the second-half loss larger.

## Decision

No acceptance-loss lifecycle was authorized. Official 2024-2026 remained unopened.

Earlier state exits can reduce median hold and preserve some aggregate pre-2024 profit, but they do not convert the parent into a repeatable, positive-median, broad day-trading Core. The same 48h/24h event family should therefore remain an Expansion diagnostic. Do not rescue it with another reclaim count, midpoint, channel, target, ML filter, risk or leverage change.

## Reproduction

- canonical file count: `64`;
- canonical data-tree fingerprint: `62bc91ae11f2a8852bb52d56b24f5e0459d256e5d2a70c8ed64a3ff7ef13a44f`;
- evaluator SHA-256: `e3bcb07a605fe3c6b8a20894f14ef820c60a48b3e9b8b633b4cebe76c8ff49ef`;
- Python `3.13.5`, NumPy `2.3.5`, pandas `2.2.3`, PyArrow `18.1.0`;
- two fresh executions produced byte-identical full `RESULT.json` with SHA-256 `a4c814b14f3e3f44f804452e1d3fb101da7e6cc15acd55f707df797289cd6503`.
