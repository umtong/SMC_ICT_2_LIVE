# RUN__R3__YT20-ALPHA-001

- claim_id: `WC-R3-YT20-ALPHA-001`
- branch: `agent/r3-transcript-alpha-001`
- base_revision: `3`
- base_commit: `2f5058bf8551a43256a8dc7a7296220ce54bb643`
- result_status: `REJECTED_PRE_HOLDOUT`
- valid_champion: `none`

## Objective and scope

Normalize the twenty registered Korean VTT transcripts once, extract source-grounded falsifiable claims, rank twelve distinct hypotheses, and immediately test the highest-value directly executable entry hypothesis. Transcript claims are hypotheses only, not profitability evidence.

The preregistered ablation compared ordinary 2x-body engulf, sweep engulf, sweep double-engulf, and sweep+FVG engulf under identical 15-minute signal, 1-minute next-event execution, structural stop, opposite pre-existing external-liquidity target, global one-slot account, and no arbitrary time exit.

## Data and causality

- Dataset: `BINANCE-UM-1M-2025-01_2026-06-R1`
- Binance public USD-M monthly archives, BTC/ETH/SOL/XRP, 786,240 rows per symbol
- Artifact SHA-256: `5994c95a0288b3cb0131a7396c557c915d5a5bfef0b381afacbdd0e8b7e32b1c`
- All range/ATR inputs use completed shifted bars.
- Zone touch schedules entry only at the next minute open.
- Target requires strict trade-through; stop wins same-bar ambiguity; gap stop uses adverse open.
- Reserved 2026-Q2 holdout was not evaluated.

## Base-cost result

| Variant | Selected | DEV1 R / PF | DEV2 R / PF | VALID R | TEST1 R | TEST2 R | DEV gate |
|---|---:|---:|---:|---:|---:|---:|---|
| ordinary_engulf | 2855 | -241.459 / 0.541 | -244.732 / 0.504 | -247.469 | -208.235 | -309.590 | false |
| sweep_engulf | 235 | -5.268 / 0.841 | -36.506 / 0.304 | -2.269 | 12.038 | -24.292 | false |
| sweep_double_engulf | 66 | 4.382 / 1.398 | -8.932 / 0.259 | 2.892 | 5.918 | -4.047 | false |
| sweep_fvg_engulf | 0 | 0.000 / 0.000 | 0.000 / 0.000 | 0.000 | 0.000 | 0.000 | false |

Liquidity context materially reduces the loss of generic engulfing, but it does not create stable positive expectancy. Double engulfing is sparse and sign-unstable. The sweep+FVG conjunction produces no eligible setup under the frozen rules.

## Cost sensitivity

| Variant | Cost | DEV1 trades / R / PF | DEV2 trades / R / PF |
|---|---:|---:|---:|
| sweep_engulf | 1.0x | 40 / -5.268 / 0.841 | 57 / -36.506 / 0.304 |
| sweep_engulf | 1.5x | 35 / -3.823 / 0.864 | 46 / -30.796 / 0.275 |
| sweep_engulf | 2.0x | 30 / -4.484 / 0.814 | 41 / -22.917 / 0.371 |
| sweep_double_engulf | 1.0x | 15 / 4.382 / 1.398 | 13 / -8.932 / 0.259 |
| sweep_double_engulf | 1.5x | 14 / 3.373 / 1.337 | 10 / -6.303 / 0.304 |
| sweep_double_engulf | 2.0x | 11 / 1.967 / 1.246 | 8 / -4.627 / 0.346 |

## Account metrics at 3% fixed risk

| Variant | Trades | Sum R | PF | Ending NAV | Daily geo | MDD | Top 5% positive-R share | NAV without top 5% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ordinary_engulf | 2854 | -1251.485 | 0.503 | 0.0000 | -8.6100% | -100.00% | 56.51% | 0.0000 |
| sweep_engulf | 235 | -56.297 | 0.714 | 0.1322 | -0.4437% | -86.37% | 46.14% | 0.0220 |
| sweep_double_engulf | 66 | 0.213 | 1.004 | 0.9063 | -0.0216% | -34.80% | 39.40% | 0.5155 |

The double-engulf subset has slightly positive arithmetic R but negative geometric growth after volatility drag and loses much of its account value after top winners are removed.

## Validation

- Pure causal execution semantics: 5 tests passed.
- Compilation: passed.
- Real-data prefix invariance at 2025-10-01: `true` for all variants.
- Same code/dataset rerun at 1.0x, 1.5x, 2.0x costs.
- Initial slow implementation was abandoned before any result was read and is not a research result.

## Verdict and next exact start

`HYP-YT20-001` and `HYP-YT20-007` are rejected before holdout. No Champion is proposed. Next is `HYP-YT20-002`: causal accumulation-range sweep/reclaim, opposite displacement/FVG, first mitigation entry, manipulation-extreme stop, opposite-range/external-liquidity target.

## Artifact hashes

- transcript_claims.jsonl: `0dea110e0f1ea4a2f3f7b2a3c944841957b67f8af4a33c7592eed026874f7503`
- hypotheses.json: `e98ca0dd87970a56cb7a4ab64a09dbcd6c82fe8f65de21a486716c72ed042ccc`
- preregistration.json: `35b5fa5a2e2d9c6f9db0f1b0fcdcbb247764774e254bb2f09342bb56cc`
- final_summary.json: `3fcbad8b02db6bfc78764d329087d3c07ea99d242d4a98d4b96723dd1cbead03`
- prefix_invariance.json: `ab3b03bc04288ca860dbde45df1b479f8923ca71230e0d47a546d6c1176f5020`
- sweep_engulf_vectorized.py: `2afdca00ccbfe5e1136dc7ff2a6e406c5aa7a32a0bf6f55058694aa6ee1f3837`
