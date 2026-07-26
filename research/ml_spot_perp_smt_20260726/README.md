# ML spot-led intermarket SMT delivery

Claim: `CLM-20260726-1908-ML-SPOT-PERP-SMT-001`

## One information unit

The system tests one causal statement:

> A completed Binance spot BTCUSDT liquidity displacement can lead Bybit BTCUSDT perpetual delivery when the perpetual is still underreacted.

In SMC/ICT language, the cash market accepts through external liquidity first, while the perpetual prints intermarket SMT by failing to deliver. One ML model decides whether that divergence represents genuine spot-led repricing or a failed cash-market sweep.

## Frozen route

1. Build external spot liquidity only from completed 15-second pivots confirmed by two completed bars on each side.
2. Retire a pool after its first wick contact. A signal exists only when the first completed one-second close accepts through the pool with aligned aggressive spot flow.
3. Reject any one-second bar that traverses both active sides because intrasecond order is unknown.
4. Require the signed Bybit five-second move to be less than half the signed spot five-second move.
5. Enter at the first valid Bybit BBO state at least 500 ms after the completed spot event: long at ask, short at bid.
6. Target the nearest still-active, causally confirmed Bybit 60-second external pool in the spot direction.
7. Stop at the nearest still-active opposite Bybit 15-second internal pivot.
8. Exit only at target, stop or a conservative source boundary. There is no elapsed-time exit.

ML cannot reverse direction, change target or stop, or create a second setup. It may only accept or reject continuation in the completed spot-displacement direction.

## Model

- one fixed `HistGradientBoostingClassifier`;
- one chronological isotonic calibration map;
- one fixed HGBT baseline using only spot displacement, lag ratio and target/stop geometry;
- 21 named full features, no feature selector;
- no model, hyperparameter, threshold, symbol, side, risk or leverage grid;
- a trade requires at least +5 bp probability-weighted expectancy after an 18 bp signal-cost contract.

## Chronology

- train: 2022-07-01 00:00–10:00 UTC, labels must resolve before 10:00;
- calibrate: 10:00–14:00 UTC, labels must resolve before 14:00;
- untouched confirmation: 14:00–24:00 UTC;
- conditional development: 2023-07-01 only after every confirmation gate passes;
- 2024–2026 are rejected before source construction.

This one-day source is a fatal information screen. It cannot enter the project ranking without a separate multi-date sequential Bybit validation.

## Gate

Untouched confirmation must contain at least 200 resolved events and 80 completed one-slot trades. The full model must beat the baseline by at least 0.02 AUC and have positive Brier skill. The account must remain positive at 18 and 24 bp with positive median trade and PF, remain positive after removing the largest 10% of winners at 18 bp, have at least three positive chronological blocks and avoid liquidation.

Failure retires the exact information unit without adjacent tuning.
