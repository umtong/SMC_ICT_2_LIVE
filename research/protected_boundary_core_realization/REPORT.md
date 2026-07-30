# Protected-boundary full-realization Core decomposition

**Result:** `RES-20260730-PROTECTED-BOUNDARY-CORE-REALIZATION-001`  
**Decision:** retired before official 2024-2026; current ranking unchanged; no live authority.

## Basis and parity

The audit retained the existing 599 volume-sponsored BTC/ETH accepted-boundary events, selected symbol sides, fixed 500 ms activation, 2ATR20 disaster stop, promoted-boundary state loss, opposite 48-hour channel exit, actual signed funding and one global slot. Only full realization at `+1.0R`, `+1.5R` or `+2.0R` was added.

The independently rebuilt Expansion path reproduced the published fixed-risk 24-bp authority closely:

| Metric | Published | Audit |
|---|---:|---:|
| Events | 599 | 599 |
| Official trades | 116 | 116 |
| 24-bp multiple | 1.4328x | 1.43218x |
| PF | 2.086 | 2.0831 |
| Winner-removed multiple | 1.0980x | 1.09750x |
| Trade-close MDD | about 4.77% | 4.83% |

This parity is sufficient to treat the fixed-R comparison as the same economic information unit rather than a new signal.

## Frozen 2022 selection

At fixed 0.5% NAV planned loss, 3x cap and 24-bp costs:

| Target | Trades | Multiple | PF | Median trade | H1 | H2 | Winner-removed | Eligible |
|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| +1.0R | 82 | 1.06232x | 1.4205 | +0.3688% | +7.18% | -0.88% | 1.02469x | No |
| +1.5R | 74 | 1.08701x | 1.5445 | +0.4484% | +6.42% | +2.14% | 1.04324x | **Yes** |
| +2.0R | 69 | 1.07710x | 1.4371 | -0.2153% | +6.99% | +0.68% | 1.04818x | No |

The frozen rule therefore selected `+1.5R`.

## Unchanged 2023 confirmation

The selected `+1.5R` route produced:

- 106 completed trades;
- 1.05436x NAV;
- PF 1.2321;
- median trade **-0.0671%**;
- median hold 5.74 hours;
- H1 +4.68%, H2 +0.73%;
- exact top-10%-of-all-trades positive-event deletion and complete rerouting: **0.99849x**, PF 0.9935, median -0.1364%.

It therefore failed two required properties of a repeatable Core:

1. the ordinary trade median was negative; and
2. exact winner deletion reduced the unchanged 2023 path below breakeven.

Official 2024-2026 was not opened. No risk, leverage, R target, partial exit, runner, session, side, funding, volume or ML rescue was attempted.

## Interpretation

The corrected protected-boundary lifecycle materially improves the long-duration Expansion, but it does not improve the fixed-R day-trading Core. Its incremental value remains tied to allowing rare accepted-delivery trades to run for days. Truncating those trades into a full-realization Core leaves a small positive total return but loses the positive-median and winner-resistant properties in unchanged 2023.

The system decomposition remains:

- **Expansion:** protected-boundary accepted delivery; strongest current target-proximity result, sparse and long-duration, not deployable alone.
- **Weak Core:** older less-crowded volume-sponsored `+1.5R` full realization; positive median and winner-resistant official path, but only about 0.012%/day.
- **Missing component:** a materially different, frequent, after-cost Core based on directly observed inventory/forced-order state rather than another channel-management variant.

## Reproduction

The compact result records the full local result and source hashes. The audit consumes only the registered canonical Bybit BTCUSDT/ETHUSDT 2021-2026H1 archives already used by the parent result.

No credentials, paper orders, testnet orders or live orders were used.
