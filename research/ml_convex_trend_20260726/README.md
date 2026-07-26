# ML convex trend onset + anti-martingale screen

Result: `RES-20260726-ML-CONVEX-TREND-001` (`CONFIRMATION_BELOW_GATE`).

## Hypothesis

A single completed 30-minute balance-to-displacement event is scored by one HGBT and one isotonic calibration map. Only positive calibrated structural expectancy opens the next-bar initial unit. The same position can add only after completed +1R and +2R progress, while the shared stop ratchets to entry and +1R. It never adds to a losing position and has no elapsed-time exit. The exact same ML-selected one-unit path is the comparator.

This is deliberately not a Donchian threshold retune: the prewritten question is whether ML onset selection plus convex anti-martingale sizing improves the identical unit-one path after 24-bp cost and winner removal.

## Causal partitions

- fit: 2023-01-01 through 2023-06-30
- isotonic calibration: 2023-07-01 through 2023-09-30
- untouched confirmation: 2023-10-01 through 2023-12-31
- 2024 opened only if every prewritten gate passed; it did not open

The preregistration SHA-256 is `f0e20d004078139de5552b8872c96a1649e2fa919dd890b62f438b7bfc60eea8`.

## Decision numbers

Confirmation contained 261 resolved labels (76 positive, 185 negative). The calibrated model achieved ROC AUC 0.5131579 and Brier skill -0.058355 versus the confirmation base rate. At 24 bp, 37 candidates passed the economic score and 35 survived the single global slot.

- one unit: -9.2680% total, -0.10566% geometric daily growth, 9.42% MDD
- pyramided: -11.3356% total, -0.13069% geometric daily growth, 11.58% MDD
- pyramided after removing the largest positive 10% event keys and rerouting: -13.7790%
- all three confirmation months were negative

The convex additions worsened both the ordinary and winner-removed paths. The exact route is killed without adjacent lookback, event, model, add-level, trail, risk, or leverage tuning. It has no ranking role and does not change live-order permission.

## Reproduce

The workflow downloads immutable-source artifact `8616632878` from run `30147824722`, installs the byte-compatible Python 3.13 scientific stack recorded in `requirements-lock.txt`, verifies the pre-registration hash inside the runner, executes the 2023-only screen, independently audits metrics and chronology, and uploads the evidence bundle. The frozen runtime is NumPy 2.3.5, pandas 2.2.3, SciPy 1.17.0 and scikit-learn 1.8.0.

Until the source artifact expires, the screen can also be run locally:

```bash
python -m pip install -r research/ml_convex_trend_20260726/requirements-lock.txt
python research/ml_convex_trend_20260726/run.py \
  --snapshot source/snapshot \
  --out research/ml_convex_trend_20260726/observed
python research/ml_convex_trend_20260726/audit.py
```

No credentials, paper orders, testnet orders, live orders, 2024 data, actual-funding replay, or Bybit-native execution replay were opened.
