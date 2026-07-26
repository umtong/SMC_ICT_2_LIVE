# Minimal ML option-surface shape first-passage — preregistration

## Claim and deliberate reduction

- Claim: `CLM-20260726-1914-ML-OPTION-SURFACE-001`
- Supersedes only the expired no-result claim `CLM-20260726-0107-OPTION-SURFACE-001`.
- One information unit: completed BTC/ETH option-surface **shape**.
- One model: pooled regularized logistic first-passage classifier.
- One action rule: cost-adjusted `LONG`, `SHORT`, or `FLAT` expected value.
- One global BTCUSDT/ETHUSDT pending/open slot.
- No model family, feature subset, probability threshold, target, stop, risk, leverage, cadence, or cost grid.

This is not an extension of the negative DVOL-level result or the negative signed option-transaction-flow/dealer-gamma result. Options are state information only; no option is traded.

## Phase 0 source gate — no outcome access

The already discovered public file `btc_option_data_toshare.parquet` (Drive file id `1g9p2Kq8op40y4ZFQQ9AJw8a9CaDThOY8`, 57,453,783 bytes, created 2024-07-29) is opened only to determine:

1. exact schema and row count;
2. timestamp semantics and date coverage;
3. whether rows are point-in-time observations or a reconstructed/end-state panel;
4. availability of symbol, option type, strike, expiry, delta, IV, underlying and open interest;
5. whether BTC only or both BTC and ETH are present.

No future return, first-passage label, action, trade, PnL, parameter choice or model metric may be computed from this 2024 file. It is source-semantic evidence only and cannot enter the official 2024 evaluation.

The immutable Tardis probe artifact from run `30165318725`, artifact `8621381122`, digest `sha256:b845bf712f65a38716c886ec8af9c42847544ed430c37c6b15a7b6a4485367bc`, is reused rather than rerun. It established accessible Deribit `options_chain` month-start files with exchange and local timestamps, expiry, strike, type, bid/ask/mark IV, underlying, delta, gamma and OI.

The source gate fails hard if timestamp/point-in-time semantics cannot be established or if the required cross-strike surface cannot be reconstructed causally.

## Primary pre-2024 sample

Only after the source gate passes, the model workflow may open fixed free Tardis month-start snippets:

- training: 2020-01-01 through 2021-12-01 month starts;
- calibration: 2022-01-01 through 2022-06-01 month starts;
- confirmation: 2022-07-01 through 2022-12-01 month starts;
- development: 2023-01-01 through 2023-12-01 month starts.

Each file is streamed in timestamp order. The frozen initial read cap is 150,000 rows per date. Increasing the cap after any label, model metric, action or PnL is prohibited. If the fixed cap cannot produce a complete surface on at least 75% of dates in a stage, the information unit fails for public-data scarcity.

Matching BTCUSDT/ETHUSDT minute bars are execution proxies only. Official 2024-2026 Bybit evaluation remains code-prohibited until all pre-2024 gates pass. A survivor must later be replayed on exact Bybit market, mark, funding and executable-price data before ranking.

## Point-in-time surface construction

A surface observation becomes available only after both the exchange timestamp and local capture timestamp are observed and the containing completed five-minute bucket has ended. The decision time is bucket end plus five minutes. No row may be used before that time.

For each asset and decision:

- front expiry: nearest expiry with 5–14 DTE;
- middle expiry: nearest expiry with 21–45 DTE;
- back expiry: nearest expiry with 60–120 DTE;
- 25-delta call: nearest positive delta to `+0.25`, maximum absolute miss `0.08`;
- 25-delta put: nearest negative delta to `-0.25`, maximum absolute miss `0.08`;
- ATM: average of the nearest call to `+0.50` and put to `-0.50`, each within `0.10`;
- IV: valid non-crossed bid/ask-IV midpoint; explicit exchange mark IV is allowed only when midpoint is unavailable and carries a fixed `mark_fraction` feature;
- all rolling changes and standardization use strictly earlier completed observations.

A row is invalid if front or middle RR25/BF25/ATM cannot be formed. Back-tenor fields may be missing and are accompanied by fixed missing indicators.

## Frozen named features

The model receives exactly these causally available values after training-only standardization:

1. front RR25;
2. middle RR25;
3. front BF25;
4. middle BF25;
5. middle-minus-front ATM slope;
6. middle-minus-front RR25 slope;
7. back-minus-middle ATM slope plus one fixed missing indicator;
8. back-minus-middle RR25 slope plus one fixed missing indicator;
9. prior one-observation change in front RR25;
10. prior one-observation change in front BF25;
11. front-tenor put/call open-interest log ratio plus one fixed missing indicator;
12. fraction of selected legs using exchange mark IV;
13. prior completed 60-minute perp return;
14. prior completed 60-minute realized volatility;
15. normalized distance to the frozen prior-60-minute buy-side liquidity pool;
16. normalized distance to the frozen prior-60-minute sell-side liquidity pool;
17. asset indicator (`BTC=0`, `ETH=1`).

No feature may use a future option update, future price, final trade outcome, MFE, MAE, later surface classification or backward-smoothed state.

## Label, model and baseline

At decision time, the preceding completed 60-minute high and low are frozen as external buy-side and sell-side liquidity. A resolved label is whichever frozen pool is reached first after the next executable minute open. Same-minute dual touches are ambiguous and excluded from model fitting. An unresolved source/day boundary is excluded from fitting but is charged as a full structural loss in account replay.

The only fitted predictor is an L2-regularized logistic regression with fixed `C=0.25`, `class_weight=balanced`, deterministic seed `20260726`, and training-only median imputation/standardization. If calibration contains at least 40 resolved outcomes and both classes, one isotonic calibration map is fitted; otherwise raw logistic probabilities are retained. This sample-size rule is frozen before outcomes.

The non-fitted comparison is the structural-distance heuristic probability

`p_up_baseline = lower_distance / (upper_distance + lower_distance)`.

The model must beat this heuristic on untouched confirmation AUC and Brier score before any development PnL is opened.

## Action and execution contract

For every eligible decision, using distances from the next executable minute open:

- `EV_LONG = p_up * upper_distance - (1-p_up) * lower_distance - round_trip_cost`;
- `EV_SHORT = (1-p_up) * lower_distance - p_up * upper_distance - round_trip_cost`;
- choose the larger positive value; otherwise `FLAT`.

Entry is the next available minute open after decision. Long exits at the frozen upper pool or frozen lower pool; short exits at the frozen lower pool or frozen upper pool. Same-minute target/stop ambiguity is loss-first. There is no elapsed-time liquidation. An unresolved source boundary is charged as the adverse frozen pool plus cost.

One global slot arbitrates chronologically; an existing pending/open position blocks later signals. Base risk is 0.5% of NAV per planned structural loss, with a fixed 3x notional cap. The identical signal and path are replayed at 12, 18 and 24 bp round-trip modeled costs. Funding must be actual before any rank-eligible result.

## Gates

The exact information unit passes only if all are true:

1. source and causal reconstruction gates pass;
2. confirmation AUC is above the structural-distance heuristic and Brier skill is positive;
3. development has at least 24 completed sparse-sample trades, both half-stages positive at 18 bp, and non-negative return at 24 bp;
4. development PF is at least 1.10 at 18 bp;
5. development remains positive after removing the top five winners and top 10% positive winners;
6. top-five positive-PnL share is at most 35%;
7. no forced liquidation or irrecoverable account path.

Failure retires this exact public option-surface-shape information unit without adjacent model, feature, threshold, risk or leverage tuning. Passing only authorizes exact Bybit reconstruction; it grants no rank or order permission.

## Seals and permissions

- Official 2024-01-01 through 2026-06-30 outcome data are unopened.
- No private credentials, paper orders, testnet orders, live orders or bank integration.
- Any result produced from the public 2024 parquet is invalid by contract because phase 0 prohibits outcome access.
