# Direct-utility Core source/result reproduction audit

## Decision

`HARD_PROGRAMIZATION_REPRODUCIBILITY_FAILURE`. The SHA-verified source bundle from PR #551 does not reproduce its attached pre-selection or official account result on the canonical Bybit segment data.

## Published versus independent replay

| Item | Published | Reproduced |
|---|---:|---:|
| Pre-2024 selected q | 0.985 | **0.970** |
| q=0.985, 15bp trades | 685 | **542** |
| q=0.985, 15bp multiple | 1.1538x | **1.0656x** |
| q=0.985, 24bp multiple | about 0.9500x | **0.9234x** |
| source-selected q=0.970, 15bp | not the published selection | **1.0040x / 939 trades** |
| source-selected q=0.970, 18bp | — | **0.9147x** |
| source-selected q=0.970, 24bp | — | **0.7680x** |

The q=0.970 path was selected only from the reproduced 2022–2023 contract. It then failed the official interval broadly, including exact top-10%-positive winner deletion at 15bp.

## What was held fixed

- source commit `9ae4886e2bfff95008d7dd85bffb00136a313532` and its SHA-verified split bundle;
- canonical BTCUSDT/ETHUSDT segment parquets for 2021 through 2026H1;
- completed 5m state, direct net-R label, fixed 500ms/next-minute representation, 3ATR/0.3% stop, +1.5R, actual funding, one global slot, 0.5% risk and 3x cap;
- fixed CPython 3.13 wheelhouse (`numpy 2.1.3`, `pandas 2.2.3`, `pyarrow 18.1.0`, `scikit-learn 1.6.1`).

Raw segment rows were compared against the canonical pandas export and matched exactly for timestamps, OHLC, turnover and completeness. Rebuilding under a second runtime produced the same changed pre-grid. The discrepancy is therefore not explained by the canonical market rows or the tested runtime versions.

## Programization verdict

The bundle carries source code and compact summaries but not the exact fitted models, scored candidate tapes, training-sample fingerprint, full trade ledgers or daily NAV used to produce the published result. At least one untransported dependency or semantic revision is material.

The first-minute acceptance sensor was not evaluated. Extending an unreproduced base would repeat the project's prior error of refining a result before proving that the underlying system is what the code actually executes.

No credentials or orders were used.