# RES-20260726-ML-OPTION-HEDGE-001

## Decision

**Hard validity: PASS_INITIAL_CAUSAL_FATAL_SCREEN. Economic status: BELOW_GATE. Ranking role: NONE_SPARSE_PRE2024_SCREEN.**

Retire the exact **Deribit option delta/gamma flow → Bybit external-liquidity first-passage** information unit. Do not tune adjacent option-flow features, Greek definitions, HGBT parameters, calibration, EV threshold, structural ranges, costs, risk or leverage.

## Minimal system

- one `HistGradientBoostingClassifier`;
- one frozen isotonic calibration;
- one cost-adjusted LONG/SHORT/FLAT structural-EV rule;
- one BTCUSDT/ETHUSDT global slot;
- frozen prior-30-minute Bybit buy-side and sell-side external-liquidity pools as target and invalidation;
- no pattern-family grid, session library, multiple models or elapsed-time exit.

In SMC/ICT terms, the model selected the draw on liquidity. The selected external pool was the target and the opposite pool was structural invalidation. Completed Deribit aggressor transactions supplied signed delta-demand and dealer-gamma-pressure state.

## Chronology

- train: 2022-01-01 through 2022-06-01 monthly first-day samples;
- calibrate once: 2022-07-01 and 2022-08-01;
- untouched confirmation: 2022-09-01 and 2022-11-01;
- 2023 development opened: **no**;
- 2024–2026 opened: **no**.

The source-only sample amendment added unopened 2022 training/calibration dates while preserving the original 300/100 resolved-row feasibility guard, all model parameters, features, labels, confirmation dates, costs, account rules and promotion gates.

## Predictive result

| Metric | Model | Distance-only baseline | Increment |
|---|---:|---:|---:|
| AUC | 0.920484 | 0.942365 | **−0.021881** |
| Brier score | 0.112087 | 0.105095 | **skill −0.066537** |

The option-flow state was predictive in absolute terms, but it made both ranking and probability accuracy worse than the causal structural-distance baseline.

## Account result

| All-in cost | Trades | Total return | Final NAV | PF | Median trade | MDD |
|---|---:|---:|---:|---:|---:|---:|
| 12 bp | 41 | −10.9678% | 8,903.22 | 0.1683 | −47.69 bp | 10.97% |
| 18 bp | 41 | −11.7481% | 8,825.19 | 0.1267 | −53.70 bp | 11.75% |
| 24 bp | 41 | −12.3369% | 8,766.31 | 0.0962 | −59.71 bp | 12.34% |

Both confirmation dates lost at every cost level. Winner-removal returns were negative and the top-five positive-PnL share was approximately 100%.

Thirty of 41 trades were conservatively stopped at public source-day boundaries. This does not explain the rejection: among the 11 naturally resolved trades, mean net return was still −7.86 bp at 18 bp.

## Reproducibility

- authoritative workflow: `30196256036`;
- authoritative artifact: `8630210182`;
- artifact digest: `sha256:036b7a728eefad45e154d39a295ec142388d5c8ebf72ebeb79276ac2f75d76ba`;
- scientific source SHA-256: `80d94063c427074b5c10896e659f06cf22a77acb94b9961c08587cd9f3b6905e`;
- result SHA-256: `466616b235b0dae9701b349e6aa6babae279a8b12641e04c062c2f27a49bcde6`;
- fit events SHA-256: `ad4e828213d1b93a8fd8a50426aa6e8cb727332d2199489e56691ad3914b193b`;
- a second workflow reproduced the scientific outputs byte-for-byte;
- no orders were submitted and live permission did not change.
