# Direct after-cost ML utility policy

Claim: `CLM-20260726-2013-ML-DIRECT-UTILITY-001`

## Why this is the current profit-first path

The project has repeatedly found that named entry patterns and first-passage classifiers either add no information beyond structural distance or produce too few cost-sized actions. This study removes the setup library.

One pooled model estimates the next executable-hour return of all four permitted Bybit contracts from completed market state. One stateful equation then chooses the highest expected **account** return after paying the cost of leaving the current position. A position can remain open for many hours. The clock only supplies new information; it never forces liquidation.

## SMC/ICT and quant explanation

- The completed rolling 24-hour high and low are higher-timeframe external-liquidity references.
- Return path efficiency, range/body displacement, volatility, volume, liquidity distance and four-asset breadth describe current delivery.
- The model ranks BTC, ETH, SOL and XRP long/short opportunities.
- The account changes its single slot only when the best predicted delivery exceeds current-position value and turnover cost.
- The opposite completed 24-hour liquidity is emergency invalidation and trails only favorably.

This is equivalent to a discretionary trader continuously asking, “Which market has the strongest remaining delivery after the real cost of abandoning what I already hold?” The answer is produced by one fixed ML model rather than a collection of setup names.

## Deliberate reduction

There is no model family, feature subset, probability threshold, named setup, target family, stop grid, risk grid or leverage grid in the alpha screen. The first account paths use unit notional at 12/18/24bp. A broad risk/leverage search opens automatically only after the complete confirmation expectancy, breadth and winner-removal gate passes.

## Sequential evidence

- train: 2021-10 through 2022-06;
- calibrate one prediction scale: 2022H2;
- untouched confirmation: 2023H1;
- conditional development: 2023H2;
- 2024-2026: prohibited in the initial workflow.

A development survivor must exceed the current `0.0573077%` daily first place at 24bp after the selected risk rule and remain positive after removing the largest positive 10% of completed trades. It still requires an exact Bybit execution and causal 2024-2026 replay before rank promotion or practical use.
