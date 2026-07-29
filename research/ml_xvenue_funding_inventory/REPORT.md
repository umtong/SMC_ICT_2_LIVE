# Cross-venue funding-inventory divergence — decision report

**Result:** `RES-20260730-ML-XVENUE-FUNDING-INVENTORY-001`  
**Decision:** `RETIRED_ECONOMIC_FAILURE_PRE2023`  
**Work Claim:** #480  
**Draft PR:** #483

## Question

Does a synchronized Bybit-minus-Binance funding-rate divergence reveal venue-specific leveraged inventory that can improve Bybit BTCUSDT/ETHUSDT day-trading decisions?

The route did not trade absolute funding. It waited for a prior-only 1.5-standard-deviation funding differential, observed one completed five-minute Bybit response after settlement, and compared:

- continuation in the crowded direction when price/OI remained accepted;
- fade of venue-specific crowding when premium/inventory normalized;
- flat.

Entries used the first later one-minute Bybit price after the fixed 500 ms activation. Stops used causally right-confirmed structure. Positions could exit only by stop, protected-origin loss, a later funding-differential normalization/reversal, or a stage-boundary NAV mark. No elapsed-time close was present.

## Source and execution corrections

The initial official Binance REST request returned HTTP 451 in the GitHub runner. This was a transport failure, not market evidence. It was replaced by 72 official Binance Vision monthly `fundingRate` archives with adjacent CHECKSUM verification. The resulting chronology contains 3,285 BTC and 3,285 ETH settlements.

Two evaluator defects were corrected before final reporting:

1. conditional 2023 action labels had been materialized mechanically before the 2022 gate; the final screen loads only 2021 and 2022 and leaves 2023 unopened;
2. adverse all-in entry/stop prices already contained execution costs, so a duplicate cost term was removed from the planned-loss denominator.

The final fixed tape contains 131 prior-only 1.5-sigma events: 66 BTC and 65 ETH. Each action has 51 fit rows in 2021 and 80 selection rows in 2022.

## Raw 2022 economics

| cost | action | return | trades | PF | top-five positive share |
|---:|---|---:|---:|---:|---:|
| 12 bp | continuation | -0.43% | 68 | 0.985 | 90.8% |
| 12 bp | fade | -20.55% | 67 | 0.215 | 100.0% |
| 18 bp | continuation | -3.88% | 68 | 0.864 | 90.5% |
| 18 bp | fade | -21.21% | 67 | 0.197 | 100.0% |
| 24 bp | continuation | -6.93% | 68 | 0.754 | 90.0% |
| 24 bp | fade | -21.61% | 67 | 0.184 | 100.0% |

The least-bad readable action was continuation at 12 bp, but it was already negative, had PF below one and depended heavily on five winners. The information source therefore did not supply a cost-surviving base engine.

## ML action-value result

| cost | policy | return | trades | PF | exact winner-deletion reroute |
|---:|---|---:|---:|---:|---:|
| 12 bp | Ridge action value | -7.30% | 38 | 0.540 | -15.27% |
| 12 bp | Logistic positive value | -8.94% | 44 | 0.506 | -17.75% |
| 18 bp | Ridge action value | -6.83% | 36 | 0.546 | -14.46% |
| 18 bp | Logistic positive value | -9.17% | 42 | 0.470 | -16.47% |
| 24 bp | Ridge action value | -8.95% | 33 | 0.364 | -13.40% |
| 24 bp | Logistic positive value | -9.46% | 41 | 0.449 | -16.69% |

The HGBT models produced constant-like negative action values and authorized no trades.

At 24 bp, the continuation logistic classifier had AUC 0.4057 and Brier 0.2679 versus 0.1120 for the constant probability. The fade classifier had AUC 0.3947 and Brier 0.2224 versus 0.0586 for the constant. Ridge rank correlations were negative for both actions. ML did not discover a hidden state; it either lost or abstained.

## Decision

The exact synchronized funding-differential family is retired before 2023.

- Calendar 2023: unopened.
- Official 2024-2026: unopened.
- Risk/leverage search: unopened.
- Ranking: unchanged.
- Credentials/orders: none.

The failure is economic, not a source, causality or execution-transport failure. More differential thresholds, rolling windows, response filters, lower costs, risk or leverage would be adjacent rescue of an information unit whose ordinary action economics are already negative.

The next route must change the information source again rather than add SMC nouns to funding events.
