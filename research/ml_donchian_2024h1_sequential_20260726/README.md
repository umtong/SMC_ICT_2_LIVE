# ML Donchian 2024H1 sequential evaluation

`RES-20260726-ML-DONCHIAN-2024H1-SEQUENTIAL-001` opens 2024H1 as the first official sequential research interval. The strategy was frozen from information available through 2023-12-31.

## Decision

The exact information unit is retired. At 24 bp the filtered account returned **+7.3021%** over 182 UTC calendar days, or **0.0387317% geometric growth per day**, versus **0.0100516%** for the unfiltered route. This remains structurally far below the 1% reference. The median completed trade was **-50 bp**, the five positive winners supplied all positive PnL, and winner-removal rerouting returned **-7.6610%**. Model MAE was worse than the constant baseline in both pre-2024 confirmation and 2024H1.

2024H1 is now seen sequential evidence. It may guide a materially different next strategy but cannot be presented as fresh independent OOS after modification.

## Evidence boundary

The evaluator, preregistration, baseline engine, event predictions, account paths, trade ledgers and checksum-identified source snapshot were independently rerun in the execution environment. `RESULT.json`, `SUMMARY.csv` and `EVENT_PREDICTIONS_2024H1.csv` were byte-identical to the preserved outputs. The durable result records their SHA-256 identities, the snapshot hashes and the exact model/account metrics.

The large local evidence archive was not committed through a partial or unverifiable transport. The repository therefore makes no claim that the full local bundle can be reconstructed from this directory alone. Reproduction must use the recorded source snapshot identities, runner SHA-256 and preregistration SHA-256 in `research/results/RES-20260726-ML-DONCHIAN-2024H1-SEQUENTIAL-001.json`.

No credentials, paper orders, testnet orders or live orders were used.
