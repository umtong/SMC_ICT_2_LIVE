# ML Donchian convex-tail selection

`CLM-20260726-2122-ML-DONCHIAN-TAIL-001`

The current rank-one Donchian all-breakout comparator is profitable but has a
negative median trade, a 20.2% win rate, more than 64% of positive PnL in its
top five winners, and negative return after removing the largest 10% winners.
This experiment does not tune the channel. It freezes the exact completed
60-minute `entry=96`, `exit=48`, `stop=2 ATR` strategy and asks one question:

> Can one causal pooled ML value model reject the ordinary losing breakouts
> while retaining enough convex trend deliveries to increase realistic
> after-cost account growth?

One fixed `HistGradientBoostingRegressor` predicts the completed structural
trade's after-24-bp R from nineteen named pre-entry features. One action rule
accepts only the simultaneous event with highest positive calibrated expected
R, otherwise it remains flat. The baseline and ML path use the same structural
events, stops, channel exits, one global slot, costs, funding reserve, NAV
engine and winner-removal rerouting.

There is no channel, feature, model, threshold, target, stop, risk or leverage
grid. A deliberately wide risk/cap search opens only after the fixed 0.5%-risk
confirmation path has positive median expectancy, positive winner-removal
return, lower concentration and higher growth than the exact same-data
all-breakout comparator.

The 2023 interval is chronological OOS for the model but is not represented as
sealed research evidence, because the baseline's 2023 concentration motivated
this experiment. Passing it opens only the frozen 2024H1 validation. 2025-2026,
credentials and every order path remain prohibited.
