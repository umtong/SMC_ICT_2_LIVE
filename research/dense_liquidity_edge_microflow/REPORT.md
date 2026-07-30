# Dense BTC prior-day liquidity-edge microflow Core successor

**Result:** `RES-20260730-DENSE-LIQUIDITY-EDGE-MICROFLOW-001`  
**Status:** `RETIRED_DEVELOPMENT_ECONOMIC_OR_DENSITY_FAILURE`  
**Confirmation/official:** unopened  
**Orders:** none

## Why this successor was valid to open

Issue #391 did not produce negative alpha evidence; it failed because its source contained only six symbol-days and eight usable interactions. Canonical Drive now contains verified continuous monthly BTCUSDT sparse-500ms archives. This successor used January through August 2023, with January-April restricted to feature-distribution freezing and May-August as the first forward development.

## Event and state

A prior-day high or low was armed only after price had been at least 0.5 one-hour ATR inside. The first observed 500ms trade-through started a five-second sensor. The fit distribution froze:

- turnover-ratio q75: `48.894327`;
- aligned high-flow impact-efficiency median: `0.005401012`.

There were `1,425` candidate minutes and `1,425` exact microflow events through August. Fit state counts were `697 flat / 49 accepted-continuation / 20 absorbed-rejection`. Development state counts were `604 / 35 / 20`.

## Fixed 24bp development account

| Route | Trades | NAV | PF | Median net trade | Median hold | Top-5 deleted / rerouted NAV |
|---|---:|---:|---:|---:|---:|---:|
| accepted continuation | 35 | 0.879514x | 0.0434 | -0.2568% | 0.0075h | 0.874549x |
| absorbed rejection | 19 | 0.934964x | 0.2012 | -0.2966% | 0.0794h | 0.918953x |
| full map | 54 | 0.822314x | 0.1031 | -0.2717% | 0.0134h | 0.803670x |

No route passed. The full map lost about `17.77%` in four development months at 24bp.

## Gross-headroom diagnosis

At zero additional cost the full map reached `1.035620x`, but deleting the five largest positive event keys and rerouting reduced it to `0.963942x`. At only 6bp the ordinary path was already `0.939110x`. The accepted and rejected branches showed the same pattern.

Therefore this is not a model-threshold or 24bp-only failure. The deterministic flow-to-price state had a small gross edge concentrated in a few events, with less than 6bp of repeatable headroom. It cannot be a realistic taker Core.

## Programization audit

The first stopped run referenced stale internal field aliases and produced no event or outcome. A later audit found that same-entry-minute exits stored the containing minute start rather than the exact microbar offset. The final authority stores the exact high/low offset, keeps adverse stop-first prices, and releases the slot no earlier than the next complete minute. The corrected PnL path was unchanged; only hold-time/funding-boundary semantics were repaired. Two fresh final runs produced byte-identical result hashes.

## Decision

Retire this exact dense successor. Do not change the five-second window, prior-day level family, q75 state boundary, 0.60 imbalance, action geometry, cost, risk, leverage or add ML. September-December, 2024-2026 and every order path remain sealed.
