# ML Donchian 2024H1 sequential evaluation

`RES-20260726-ML-DONCHIAN-2024H1-SEQUENTIAL-001` opens 2024H1 as the first official sequential research interval. The strategy is frozen from information available through 2023-12-31.

## Decision

The exact information unit is retired. At 24 bp the filtered account returned **+7.3021%** over 182 calendar days, or **0.0387317% geometric growth per day**, versus **0.0100516%** for the unfiltered route. This remains far below the 1% reference. The median trade was **-50 bp**, the five positive winners supplied all positive PnL, and winner-removal rerouting returned **-7.6610%**. Model MAE was worse than the constant baseline in both pre-2024 confirmation and 2024H1.

2024H1 is now seen evidence. It may guide a different next strategy but cannot be presented as fresh independent OOS after modification.

## Reproduction

```bash
python research/ml_donchian_2024h1_sequential_20260726/reconstruct_evidence.py
```

The evidence bundle contains the preregistration, runner, baseline engine, full account paths, trade ledgers, event predictions, summaries and checksum-identified dataset manifest. No credentials or orders are used.
