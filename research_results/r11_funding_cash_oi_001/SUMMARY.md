# RES-20260726-FUNDING-CASH-OI-001

## Decision

Hard-valid initial causal screen; economically `TESTED_BELOW_GATE`. The exact actual-funding-transfer-notional × OI-reaction formulation is retired without opening 2024-2026.

## SMC/ICT explanation

Actual transferred USDT is the objective liquidity pressure. The funding sign identifies payer and receiver inventory pools. Post-settlement OI contraction or expansion aligned with price movement is displacement and a balance-sheet liquidity run. Prepaid OI contraction followed by extension, stalled contraction and reclaim is sweep exhaustion. A survivor would later enter only on the first causal displacement-imbalance/FVG retracement.

## Result

- 96/96 source files passed.
- BTCUSDT and ETHUSDT passed the source-coverage gate.
- 41 fit and 45 development settlements; 172 causal event rows.
- 512 frozen cells; zero gate passes.
- Positive candidates at 12/18/24 bp: 0/0/0.
- 176 cells traded in development, but zero reached 12 fit plus 12 development trades.
- Maximum development count: five.
- Maximum active mean gross markout: 4.493741 bp, only 37% of the minimum 12-bp cost.
- Payer closure reached at most one development trade; prepaid reversal produced none.
- The best active receiver-releverage cell had one fit and two development trades and lost at all costs.

## Boundary

Do not tune adjacent transfer quantiles, OI thresholds, confirmation bars or horizons. Reopen only with continuous point-in-time balance-sheet coverage or a materially different primary information source/payoff.
