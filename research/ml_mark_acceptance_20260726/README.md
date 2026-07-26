# Minimal ML mark/index acceptance router

Claim: `CLM-20260726-1940-ML-MARK-ACCEPTANCE-001`

## One SMC/ICT mechanism

The last completed five minutes of executable Bybit midpoint form a causal external-liquidity range. A completed quote second raids exactly one range boundary. After one further completed response second and a fixed 100 ms decision-to-entry delay, two structural objectives are frozen symmetrically around the raided boundary.

- If execution price, mark, index, aggressive flow and open interest accept the raid, the same-side objective is the continuation draw on liquidity.
- If execution price raids but mark/index and flow fail to accept, the opposite objective is the rejection draw on liquidity.
- One calibrated ML probability chooses the upper objective, lower objective or flat through an exact cost-adjusted expected-value equation.

The model does not create a pattern library. Target and stop are the two frozen structural objectives, same-second ambiguity is adverse, and there is no elapsed-time exit.

## Deliberate reduction

- one pooled `HistGradientBoostingClassifier`;
- one isotonic calibrator;
- exactly twelve named features;
- one 18 bp signal-cost EV rule;
- one global BTCUSDT/ETHUSDT slot;
- no model family, feature, threshold, payoff, risk or leverage grid.

## Chronology

- train: 2022-01-01, 2022-03-01, 2022-05-01;
- calibration: 2022-07-01;
- untouched fit confirmation: 2022-09-01, 2022-11-01;
- conditional development: odd-month first days of 2023;
- 2024-2026 are rejected by code.

## Economic contract

Actual Bybit BBO after 100 ms is used for entry. Position size is the minimum of 0.5% NAV structural-loss sizing, 3x notional, and 20% of displayed top-quote size. Identical gross paths are replayed at 12, 18 and 24 bp. The largest 10% of positive event keys are removed before rerouting the one-slot account.

The 2023 partition cannot open unless the untouched 2022 confirmation simultaneously beats the stronger structural-distance or mark-acceptance baseline, improves Brier score, produces enough cost-sized actions, remains positive after costs and winner removal, and is positive on both confirmation dates.

## Reproduction

```bash
python -m pip install numpy==2.1.3 pandas==2.2.3 requests==2.32.4 scikit-learn==1.6.1 pytest==8.3.4
PYTHONPATH=research/ml_mark_acceptance_20260726 pytest -q research/ml_mark_acceptance_20260726/test_run.py
PYTHONPATH=research/ml_mark_acceptance_20260726 python research/ml_mark_acceptance_20260726/run.py self-test
PYTHONPATH=research/ml_mark_acceptance_20260726 python research/ml_mark_acceptance_20260726/run.py probe --cache /tmp/ml-mark-acceptance --output research_runs/ml_mark_acceptance_20260726/r11
PYTHONPATH=research/ml_mark_acceptance_20260726 python research/ml_mark_acceptance_20260726/run.py run --cache /tmp/ml-mark-acceptance --output research_runs/ml_mark_acceptance_20260726/r11
```

No credentials or orders are used.
