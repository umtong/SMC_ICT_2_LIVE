# Four-asset common-state direct-utility Core

**Result:** `RES-20260730-FOUR-ASSET-COMMON-DIRECT-UTILITY-001`  
**Decision:** retired after official broad economic failure; target not met; no live authority.

## Question

Can one normalized market-state relation, without a symbol identifier, map completed five-minute price, volatility, turnover, open interest, premium and account-ratio state to direct cost-after action value across BTC, ETH, SOL and XRP?

Each symbol was represented against the median state of the other three. The same long/short action geometry, fixed 500 ms execution, actual funding, 0.5% NAV risk, 3x cap and one global slot applied everywhere. CatBoost was deterministic, used no bootstrap/random feature sampling and predicted direct 24-bp account return rather than direction accuracy.

## Pre-2024 result

The unchanged q=0.97 route survived the fixed gate:

- 2022: 1.06023x, 505 trades, PF 1.043; exact top-five positive-event deletion and full rerouting 1.05990x.
- 2023: 1.10360x, 478 trades, PF 1.079; unchanged rerouting 1.10953x.

No symbol, side, model, risk or lower-cost filter was added before official replay.

## Official 2024–2026

Annual expanding models were released six hours after each new UTC year. The continuous path produced 1,253 completed trades:

| cost | multiple | daily geometric | PF | realized-trade MDD | winner-reroute multiple |
|---:|---:|---:|---:|---:|---:|
| 12 bp | 0.96313x | -0.004119% | 0.990 | 14.95% | 0.91336x |
| 18 bp | 0.78571x | -0.026440% | 0.934 | 23.25% | 0.71036x |
| 24 bp | 0.65001x | -0.047222% | 0.882 | 36.02% | 0.60351x |

At 24 bp, 2025H2 was approximately flat and every other half-year lost. Median holding was 146 minutes. The largest ten winners supplied only 2.47% of positive PnL, so this was not a few-jackpot failure; it was frequent negative compounding.

## Programization audit

The first official process retained multiple annual models, full score tapes and all four minute markets simultaneously and was terminated by memory pressure. It produced no account result. The corrected run trained and scored one year at a time, retained only the frozen q>=0.97 candidates and calculated the realized path before any liquidation-value expansion. Strategy, features, model, threshold, costs and account rules were unchanged.

## Decision

The same normalized meaning across four markets did not persist after 2023. Do not rescue the family with q, symbol, side, CatBoost parameter, stop, target, cost, risk or leverage changes. The next research family must use a materially different information source rather than another completed-bar price/OI/premium model.

No credentials, paper orders, testnet orders or live orders were used.
