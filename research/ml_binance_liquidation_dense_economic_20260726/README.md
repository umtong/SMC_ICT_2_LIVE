# Dense Binance forced-liquidation ML economic stage

This is the conditional economic continuation of `CLM-20260726-2020-ML-BINANCE-LIQ-DENSE-001`. It executes only after the official Binance Vision `liquidationSnapshot` source gate produces a decision-ready `PASS` artifact.

## Minimal profit-first system

- All completed forced-liquidation minute buckets are candidates; there is no liquidation-size threshold grid.
- One pooled HGBT estimates whether the already-confirmed upper or lower external-liquidity pool is reached first.
- The structural-distance probability is the non-fitted baseline.
- One expected-value equation subtracts the full 12/18/24-bp cost before choosing `LONG`, `SHORT`, or `FLAT`.
- One global position blocks every market until structural target, structural stop, or boundary-unresolved adverse settlement.
- There is no elapsed-time liquidation.
- Winner removal deletes event identities before complete chronological signal and slot rerouting.

## Causal source and market handling

The source PASS determines the exact checksum-verified liquidation archives. Binance Vision monthly one-minute USD-M kline and funding archives are then independently checksum verified. Missing minutes are never interpolated: every rolling feature, pivot, label, and position is invalidated across the gap and state restarts only after the entire causal window is complete.

A fifteen-minute swing is known only after two right-side bars have completed. A confirmed pool is removed once consumed. The event minute completes, a fixed five-second operational delay passes, and entry is the next exact one-minute open.

## Frozen chronology

- fit: 2021 through 2022H1;
- calibration: 2022H2;
- untouched confirmation: 2023H1;
- conditional development: 2023H2;
- official 2024H1 remains sealed in this stage.

A base survivor must outperform structural distance in AUC and Brier score, produce at least fifty completed global-slot trades, remain positive at 24 bp with a positive median, be positive in both halves, remain positive after top-five and top-10%-positive event removal, keep top-five positive-PnL share at or below 35%, and avoid forced liquidation or irrecoverable account damage in both confirmation and development.

Failure retires this exact information unit without model, feature, threshold, target, stop, risk or leverage rescue. Passing freezes the system through 2023-12-31 and immediately opens exact-Bybit reconstruction followed by official 2024H1. Risk and notional are then explored broadly for maximum sustainable geometric growth, not capped at 1%.
