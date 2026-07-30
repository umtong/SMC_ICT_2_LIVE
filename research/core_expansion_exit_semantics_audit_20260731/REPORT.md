# Core + Expansion exit-semantics programization audit

## Decision

`COMPLETED_LATENT_DEFECT_FIXED_ECONOMICALLY_IMMATERIAL`.

The parent logic and event surface were frozen. This audit corrected only two potential execution/account mismatches:

1. at a structural-exit activation minute, a pre-existing hard stop has adverse gap precedence and a still-live fixed Core target caps a favorable gap before the structural market exit; the later high/low of that minute is unavailable;
2. a position whose strategy exit timestamp equals a UTC NAV boundary is closed cash at that boundary, not marked again at the previous minute close.

## Programization result

Seven focused synthetic regressions passed. The corrected source then rebuilt the complete parent event/action/account path twice; all 32 outputs were byte-identical.

Across the exact parent Core and Core+causal-runner routes:

- target gap at structural activation: **0 cases**;
- adverse stop gap at structural activation: **0 cases**;
- strategy exit exactly at a UTC daily boundary: **0 cases**.

The parent and corrected event Parquet files are byte-identical. The official 24bp Core and hybrid trade ledgers are also byte-identical.

## Economic comparison

| Policy | Period/cost | Parent | Corrected | Delta | Winner-rerouted delta |
|---|---|---:|---:|---:|---:|
| Core | 2022-2023, 24bp | 1.149659x | 1.149659x | 0 | 0 |
| Hybrid | 2022-2023, 24bp | 1.224372x | 1.224372x | 0 | 0 |
| Core | 2024-2026, 24bp | 1.090296x | 1.090296x | 0 | 0 |
| Hybrid | 2024-2026, 24bp | 1.158970x | 1.158970x | 0 | 0 |

Daily marked MDD and all half-year returns are unchanged at every 12/18/24bp path.

## Interpretation

The audited code path was logically incomplete and should remain fixed for future data, but it did not occur in the historical parent sample. It therefore cannot explain why the system remains far below 1%/day, why the final two half-years are weak, or why the runner remains a meaningful share of PnL.

Do not change the parent result, ranking or live authority. Preserve the corrected precedence and UTC-boundary regression tests in reusable execution code. The next research step must return to missing economic information, not continue polishing this immaterial code path.
