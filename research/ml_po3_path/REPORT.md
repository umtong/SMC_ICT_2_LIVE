# Active-candle PO3 action-value research

Result: `RES-20260729-ML-PO3-PATH-001`  
Claim: `CLM-20260729-2114-ML-PO3-PATH-001` / issue #401

## Hypothesis

The retained Korean caption corpus describes Power of Three as a path, not a standalone candle pattern: accumulation first, a one-sided trap or manipulation second, and distribution last. The implementation therefore froze the first part of an active UTC-aligned 4h or day candle as the accumulation range, then compared rejection, accepted same-side distribution and flat actions from completed information.

No prior-day/swing/session external-liquidity level, FVG, order block, fixed RR, forced holding duration or scheduled close was required. The selected accepted-distribution action waited for two consecutive completed 5m closes outside the frozen range and used a passive retracement entry rather than chasing the breakout.

## Important implementation corrections

The earliest prototype was invalid as a representation of the hypothesis. It treated almost every small 4h range break as manipulation and generated more than 2,400 trades per year. The corrected engine added accumulation compression/path state, meaningful range-relative excursion and consecutive acceptance logic.

Additional defects discovered during the research loop were corrected before the reported result:

1. nonconsecutive outside closes had been counted as acceptance;
2. an unfilled limit could occupy the global slot after the active higher-timeframe candle ended;
3. pending-order expiry had been conflated with the lifecycle of a filled position;
4. the first cost model charged every outcome a flat 12 bp even though the tested entry and target were resting maker orders and only the stop was taker;
5. positive price-unit expectation concealed that narrow-stop losses consumed the full 0.5% account loss budget more often than large-stop winners received equivalent notional.

The corrected base path uses maker entry and target, taker stop plus an additional stop spread/slippage allowance, exact funding, 500 ms activation represented by the first later observable 1m price, one-basis-point passive penetration and adverse-first same-minute ambiguity.

## Deterministic result

The strongest all-pre-2024 accepted-distribution state used:

- active UTC day;
- first 240 minutes as accumulation;
- two consecutive completed 5m closes outside the range;
- entry halfway between the breached boundary and confirmation close;
- stop at the opposite accumulation boundary;
- target one range extension beyond the breached boundary;
- compressed/choppy accumulation and efficient accepted path state.

With order-type costs it was positive in each pre-2024 calendar year, but only generated 15–37 trades annually. More importantly, chronological selection exposed instability: the strongest routes chosen from 2021–2022 generally lost in 2023, and only four of 3,850 effective grid combinations were positive in all three years.

The fixed deterministic path failed the first official 2024H1 opening interval:

| interval | trades | return | PF | win rate |
|---|---:|---:|---:|---:|
| 2024H1 | 25 | -2.1973% | 0.663 | 48.0% |

Later calendar diagnostics occasionally recovered, but they are not a substitute for the failed opening gate and are not presented as a continuous official NAV result.

## ML action-value result

A pooled `HistGradientBoostingRegressor` used only pre-entry information: accumulation efficiency and rotations, excursion depth, completed-bar acceptance quality, path efficiency, range-relative volatility, OI and account-ratio changes, prior completed-period returns, time state, symbol/direction and known stop/target geometry.

Model development was chronological:

- fit 2021, forward-score 2022;
- fit 2021–2022, forward-score 2023;
- choose model and absolute action-value threshold by worst forward log growth, with at least 15 trades in each forward year;
- refit once through 2023-12-31 and freeze before 2024.

The forward development results were positive and substantially broader:

| interval | trades | return | PF | top-five positive share |
|---|---:|---:|---:|---:|
| 2022 forward | 115 | +4.8781% | 1.217 | 8.65% |
| 2023 forward | 131 | +4.9440% | 1.190 | 7.46% |

The frozen model nevertheless failed 2024H1:

| interval | trades | return | PF | win rate |
|---|---:|---:|---:|---:|
| 2024H1 | 60 | -1.1876% | 0.919 | 53.3% |

The ML filter therefore improved pre-2024 breadth and reduced winner concentration, but did not learn a stable enough representation of the distribution state to survive the official opening regime.

## Adjacent paths rejected

- The broad 4h rejection family was negative under a uniform 12 bp diagnostic. Correct order-type fees made a narrow subset slightly positive, but the edge disappeared under small adverse cost changes and its growth was orders of magnitude below the project objective.
- A 50% first-target / 50% runner structure raised nominal win rates to roughly 72–79%, yet its best broad path still lost in 2021 because many small first-target/breakeven outcomes did not repay full stops.
- A broad rejection ML filter lost in both 2022 and 2023 forward tests; ML was not used as a rescue for a negative base family.
- Daily and 4h absolute-volatility gates that looked good in 2021–2022 became sparse or negative in 2023 and were rejected as volatility-threshold overfit.

## Decision

This exact active-candle PO3 information unit is retired as an economic failure. The official opening interval is negative, the positive pre-2024 surface is sparse, and the best frozen ML policy remains far from the required 1% UTC geometric daily growth.

No risk, leverage, adjacent SMC checklist, 2024-aware threshold or cosmetic model change should be used to rescue it. The reusable lesson is that PO3 must not be reduced to any range break and that order-type economics can reverse a marginal conclusion, but neither correction creates a sufficiently strong deployable alpha here.
