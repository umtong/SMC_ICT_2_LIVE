# Bybit atomic matching-event sweep topology

Claim: `CLM-20260726-0542-MATCH-SWEEP-001`  
Result: `RES-20260726-MATCH-SWEEP-001`  
Status: tested below gate; exact dependency retired; 2024 and later remained unopened

## Hypothesis

A single aggressive order can execute against several resting prices at one exchange timestamp. The completed event therefore exposes a price-level fan-out that an ordinary candle or generic trade-rate burst does not preserve. The study asked whether that topology, together with the first causally observable second of response, separates:

- queue-depleting sweeps that continue in the taker direction; and
- terminal sweeps that reject and reverse after the aggressive order is exhausted.

The information unit was a completed Bybit public-trade group sharing the exact exchange timestamp and taker side. Timestamps containing both taker sides were excluded. The active generic event-tape study uses inter-trade speed, episode notional and episode-level impact efficiency; this study instead used within-timestamp executed-price topology. It also differs from the retired metaorder-cadence study, which linked repeated child clusters across time.

## Frozen contract

The independent confirmation contract was committed as `preregistration_midmonth_confirmation_v1.json` at `099b785228aec68e6b836cbdaa971274bef98b73` before any confirmation file was opened.

- Training: BTCUSDT and ETHUSDT first-day partitions from January through June 2023.
- Confirmation: February 15, April 15, June 15, August 15, October 15 and December 15, 2023.
- Event: at least five distinct executed prices and at least one basis point of completed price span.
- State: completed prior 60/300-second trade state, price-level concentration and entropy, and responses at 0.1/0.25/0.5/1.0 seconds.
- Entry: first same-symbol public trade at or after event timestamp plus 1.1 seconds.
- Exit: first same-symbol public trade at or after entry plus one hour.
- Model: frozen `HistGradientBoostingRegressor`; frozen absolute prediction threshold `23.81534927035741` basis points.
- Account: one global BTC/ETH slot; exact simultaneous entries ranked only by the frozen absolute prediction.
- Cost stress: 12, 18 and 24 basis points round trip.

The fatal gate required at least 40 trades, positive mean at 18 basis points, positive median at 12 basis points, positive top-10%-removed mean at 12 basis points, at least four of six positive dates, and no more than 35% of positive gross PnL from the largest winner.

## Original confirmation run

The original frozen run produced 56 global-slot trades:

| Metric | Result |
|---|---:|
| Gross mean | +13.9153 bp/trade |
| Net mean at 12 bp | +1.9153 bp/trade |
| Net mean at 18 bp | -4.0847 bp/trade |
| Net mean at 24 bp | -10.0847 bp/trade |
| Net median at 12 bp | -5.6690 bp/trade |
| Top-10%-removed net mean at 12 bp | -13.2854 bp/trade |
| Positive dates at 12 bp | 2 of 6 |
| Largest winner share of positive gross PnL | 18.03% |

Only the sample-count and largest-winner-share gates passed.

## Independent reconstruction

The temporary original evaluator was not preserved after an execution-environment reset, so the raw files were reacquired and independently reconstructed from the frozen contract. All 24 official Bybit source files matched their preregistered SHA-256 values. The reconstruction produced 46 global-slot trades:

| Metric | Result |
|---|---:|
| Gross mean | +21.5583 bp/trade |
| Net mean at 12 bp | +9.5583 bp/trade |
| Net mean at 18 bp | +3.5583 bp/trade |
| Net mean at 24 bp | -2.4417 bp/trade |
| Net median at 12 bp | -3.4371 bp/trade |
| Top-10%-removed net mean at 12 bp | -7.4478 bp/trade |
| Positive dates at 12 bp | 2 of 6 |
| Largest winner share of positive gross PnL | 17.35% |

The aggregate and trade count do not exactly reproduce the original implementation, so the result is not represented as a byte-identical hard-valid reproduction. The decision is nevertheless invariant: both implementations fail positive net median, top-winner-removal robustness and four-of-six date breadth, and neither survives 24-basis-point cost.

## Decision

`RETIRE_EXACT_DEPENDENCY`.

Do not use the confirmation partitions to tune event span, level count, response horizon, model parameters, prediction threshold, symbol inclusion or holding period. Do not salvage BTC-only after observing the confirmation split. Do not open 2024 for this rule. Reopen only if the information unit changes materially, such as independently observed displayed-depth refill or participant identity that is not present in the public trade tape.

This result is not inserted into the strategy ranking and does not change live-order permission.

## Reproduction

The independent reconstruction is implemented in `evaluate_confirmation.py`. It accepts the directory containing the 24 SHA-identified Bybit files and emits the reconstruction trade ledger and metrics. Because the original implementation was not preserved, `confirmation_decision.json` records both the original aggregate and the independent reconstruction rather than claiming exact equivalence.
