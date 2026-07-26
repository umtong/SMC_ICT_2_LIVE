# Minimal ML Coinbase institutional-flow relay

Claim: `CLM-20260726-1108-COINBASE-FLOW-001`

## One SMC/ICT mechanism

A completed 15-second Coinbase BTC-USD or ETH-USD displacement defines external delivery direction. Bybit may still remain inside the completed prior five-minute dealing range. The system freezes that Bybit range before the Coinbase window, waits a conservative cross-provider delay, and enters only when one calibrated model says Coinbase initiative is likely to deliver Bybit to the directional external range boundary before the opposing boundary.

The model does not choose symbol, direction, window, entry delay, target, stop, risk or leverage. It accepts or rejects one already-defined external-displacement/Bybit-underreaction event.

## Minimal system

- one standardized L2 logistic regression with fixed `C=0.5`;
- one structure-only logistic baseline;
- one isotonic calibration map;
- exactly ten normalized features;
- one binary target-before-stop label;
- one cost-adjusted continuation/flat equation;
- 2-second and 5-second execution paths as latency stress, not separate strategies;
- one global BTC/ETH slot;
- no elapsed-time exit;
- observed BBO, exact historical Bybit funding and 12/18/24 bp all-in replay;
- 1% planned structural risk and 3x notional cap;
- BitMEX and every closing-provider dependency prohibited.

## Frozen chronology

The only free public source dates are first-day samples:

- train: 2022-01-01;
- calibration: 2022-03-01;
- untouched fit confirmation: 2022-05-01;
- conditional development: 2022-07-01, 2022-09-01, 2022-11-01;
- 2023 and 2024-2026 stay sealed in this fatal screen.

A fit failure retires the exact information unit without model, feature, event, threshold, delay, target/stop, risk or leverage tuning.
