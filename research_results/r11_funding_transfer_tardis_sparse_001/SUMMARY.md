# RES-20260726-FUNDING-TRANSFER-TARDIS-SPARSE-001

## Decision

Hard-valid initial causal screen; economically `TESTED_BELOW_GATE`. The exact funding-rate plus aligned-premium settlement-transfer formulation is retired without opening 2024-2026.

## SMC/ICT explanation

The settled funding debit objectively identifies the vulnerable payer-side liquidity pool. Completed post-settlement displacement tests a delayed payer flush; extension and reclaim tests a completed liquidity sweep; premium contraction tests a snapback toward the index anchor. The proxy waits one extra bar, and any survivor would later be allowed to enter only on the first causal retracement into the displacement imbalance/FVG.

## Result

- 96/96 Tardis first-day source files passed integrity and causal field checks.
- BTCUSDT and ETHUSDT passed the predeclared source-coverage gate.
- 720 frozen cells; zero gate passes.
- Positive candidates at 12/18/24 bp: 0/0/0.
- 261 cells traded in development, but none reached 12 fit and 12 development trades.
- Maximum development trade count was 3; prepaid sweep reversal generated none.
- Best active mean gross markout was 6.6590 bp, below the minimum 12-bp cost stress.
- The one-trade best active cell returned -0.0534%/-0.1134%/-0.1734% at 12/18/24 bp.

## Boundary

Do not tune adjacent funding/premium quantiles, confirmation bars or horizons. A new study must change the primary information unit—for example actual aggregate funding-transfer notional and causal OI balance-sheet reaction—or obtain continuous point-in-time coverage.
