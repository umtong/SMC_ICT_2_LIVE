# Minimal ML L2 hazard local trigger

Claim: `CLM-20260726-1734-HAZARD-OCO-ML-001`  
Result: `RES-20260726-ML-L2-HAZARD-LOCAL-TRIGGER-001`

## Trader-readable mechanism

The model predicts **when balance is likely to expand**, not whether the delivery will be bullish or bearish.

1. Completed 100ms Bybit top-five order-book and aggressive-flow state describes the current balance.
2. One HGBT estimates whether executable midpoint will make a 40bp absolute first passage within 30 seconds.
3. A score above the frozen 99th percentile creates one local monitoring state. It does not place an exchange order.
4. Local software watches equal 4bp internal buy-side and sell-side trigger levels.
5. The first exact Bybit raw trade-through reveals delivery direction.
6. Only then is one marketable order simulated after 100ms or 300ms.
7. If the same exchange-local timestamp crosses both levels, the event is rejected without an order.
8. A filled position exits only at its frozen structural target, protective stop or conservative source-boundary stop. There is no elapsed-time liquidation.

In SMC/ICT terms, ML attempts to identify an imminent **balance-to-imbalance transition**, while actual displacement selects direction. In quant terms, this is a direction-neutral hazard classifier followed by a single-order first-passage execution rule.

## Minimal system

- one `HistGradientBoostingClassifier`;
- eight completed-state features;
- one 40bp/30s label;
- one 99th-percentile score threshold;
- one 4bp local trigger mechanism;
- exactly three target/stop cells: 40/20bp, 60/25bp and 80/30bp;
- 100ms base and 300ms entry-latency stress;
- one global monitoring/pending/open slot;
- zero resting exchange entry orders before a local trigger and at most one exchange entry order afterward;
- fixed 1% planned loss, 3x notional cap and 0.1% prior-three-second traded-notional capacity;
- identical 12/18/24bp cost paths;
- no directional model, secondary pattern, time liquidation, risk search or leverage rescue.

## Causal data contract

The screen reuses the SHA-identified completed 100ms BTCUSDT state from parent artifact `8626169763` and the exact raw Bybit trade stream for 2022-07-01. The fit day is split chronologically:

- 00:01–12:00 UTC: model training;
- 12:00–18:00 UTC: score calibration;
- 18:00–24:00 UTC: fit-account test.

Untouched 2023-07-01 can open only after every fit gate passes. It did not open. Every 2024–2026 source is prohibited.

The runtime schema exposes `decision_us`, so the pre-outcome correction derives the decision stride from `decision_us // 100000` instead of requiring a nonexistent stored `bin` column. The corrected runner SHA-256 is `46b3ba0f1875ba66c827d3e48c044dabf3108890446fba9e3f0542e4ada3bb0d`.

## Result

Workflow `30197559374` completed successfully and uploaded artifact `8630589328`, digest `sha256:8b260029bb824e8fd879dafbeaf7b28c99d97bf3ce31fe9b2768e1ec5ebc8ff3`.

The model identified hazard, but it did not add information beyond the simplest frozen volatility baseline:

- training rows: **8,550**;
- positive training labels: **339**;
- calibration rows: **3,430**;
- HGBT calibration AUC: **0.750799**;
- 30-second realized-volatility baseline AUC: **0.811759**;
- AUC lift: **−0.060960**;
- fit-gate survivors: **0**.

All three structural payoff cells lost after 18bp:

| Cell | 100ms trades | 100ms return | Median trade | PF | 300ms return |
|---|---:|---:|---:|---:|---:|
| 40/20bp | 4 | −0.7509% | −38.89bp | 0.00 | −0.7329% |
| 60/25bp | 3 | −0.7231% | −43.76bp | 0.00 | −0.7193% |
| 80/30bp | 1 | −0.4858% | −48.00bp | 0.00 | −0.4858% |

The 24bp paths were more negative. Untouched development stayed unopened; no 2024–2026 source or order path was opened.

## Decision

Retire this exact completed-100ms top-five L2 absolute-hazard local-trigger dependency. Do not tune the model, feature set, threshold, entry offset, targets, stops, latency, risk rate or leverage. The information target is statistically learnable but economically inferior to simple recent volatility, and the permitted single-order payoff did not cover realistic costs.

The older two-entry-order `RES-20260726-HAZARD-OCO-V2-001` is hard-invalid under the project's one-new-entry-order global contract and is retained only as superseded evidence.
