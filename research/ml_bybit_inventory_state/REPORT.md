# ML Bybit leveraged-inventory state transition — decision report

**Result:** `RES-20260729-ML-BYBIT-INVENTORY-STATE-001`  
**Decision:** ECONOMIC FAIL; exact family retired before 2024.  
**Claim:** `CLM-20260729-ML-BYBIT-INVENTORY-STATE-001` / GitHub issue #382.

## Mechanism tested

A completed 15-minute Bybit price/volume shock was combined with causal OI, account-ratio, premium/mark-index basis and BTC/ETH relative state. The ML route estimated future state value and chose continuation, reversal or flat. The interpretable base route isolated new-position accumulation: OI shock z-score above 1, non-saturated account ratio and premium, continuation in the shock direction, structural stop, and exit only when two-hour price trend and OI accumulation jointly lost state. No elapsed-time close was used.

## Fixed execution and account contract

- BTCUSDT and ETHUSDT; one global pending/position slot.
- Completed five-minute decisions; fixed 500 ms latency; first executable minute open strictly after activation.
- 24 bp all-in round-trip stress plus actual funding events.
- Stop gaps execute at the adverse observed minute open; stops take precedence over later state exits.
- Initial risk was fixed at 0.5% NAV with a 3x notional cap so sizing could not manufacture alpha.
- Stage-boundary exposure is marked, not strategy-closed.

## ML dynamic-policy result

| interval | NAV | return | geometric daily growth | trades | PF | MDD | median account return |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2022 selection | 8883.28 | -11.17% | -0.0324% | 403 | 0.928 | 33.17% | -0.500% |
| 2023 frozen confirmation | 3437.78 | -65.62% | -0.2921% | 680 | 0.607 | 66.44% | -0.500% |

The 2021-trained event-tail diagnostic briefly produced +80.4% in 2022, but the frozen 2023 path generated only three trades and lost 4.62%. The broader state-loss implementation removed that sparsity illusion and exposed a persistently negative policy.

## Interpretable OI-accumulation continuation result

| year | NAV | return | geometric daily growth | trades | PF | MDD | median account return |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2021 | 8089.01 | -19.11% | -0.0581% | 375 | 0.754 | 19.90% | -0.182% |
| 2022 | 8355.23 | -16.45% | -0.0492% | 373 | 0.798 | 22.01% | -0.215% |
| 2023 | 7672.68 | -23.27% | -0.0726% | 316 | 0.687 | 23.27% | -0.252% |

The economic branch was negative in every pre-2024 year. Its least-bad selection still lost 19.11% in 2021, 16.45% in 2022 and 23.27% in the frozen 2023 confirmation. This is not a candidate for risk or leverage optimization.

## Decision

The exact family is closed. Official 2024H1 was not opened, the cumulative strategy ranking is unchanged, and no live or paper order was authorized. The next study must change the economic source of alpha rather than tune OI thresholds, model confidence, stop distance, target multiple, cost assumptions or leverage.

## Reproducibility

`CONTRACT.json` fixes the evaluation contract. `explore.py`, `dynamic_policy_fast.py` and `continuation_rule.py` contain the causal feature/event construction and account replay. `RESULT.json` records dataset manifest fingerprints and source SHA-256 values. Large local feature/trade tables are not committed to GitHub; the canonical Drive datasets are the source of truth.
