# RUN REPORT — Direct after-cost ML utility

Current cumulative first place remains `FIRST-20260726-DONCHIAN-ALL-A70626D9E484`, stage `PRELIMINARY_CAUSAL_BINANCE_PROXY`, with `0.0900854%` geometric daily growth at 12bp and `0.0700189%` at 24bp. Its 12bp gap to the 1% objective is `0.9099146` percentage points per UTC calendar day. The direct-utility candidate did not challenge it because the frozen calibration collapsed the model score to zero and authorized no confirmation trade.

## Claim and result

- Claim: `CLM-20260726-2013-ML-DIRECT-UTILITY-001`
- Result: `RES-20260726-ML-DIRECT-UTILITY-001`
- Validation: `VAL-20260726-ML-DIRECT-UTILITY-001`
- Hard validity: `PASS_INITIAL_CAUSAL_FATAL_SCREEN`
- Economic status: `CONFIRMATION_BELOW_GATE`
- Ranking role: none
- Decision: retire the exact information unit without adjacent tuning

## Explainable strategy logic

One pooled `HistGradientBoostingRegressor` estimated the next executable-hour signed return for BTCUSDT, ETHUSDT, SOLUSDT and XRPUSDT from completed hourly return, volatility, path-efficiency, volume, breadth and causal liquidity-distance features. A single account rule compared `KEEP`, `SWITCH` to any long or short contract, and `FLAT` after immediate turnover and adverse funding reserve. The one global slot could change only when another state had higher positive expected utility. An open position used the already-known rolling 24-hour opposite extreme as a structural stop. There was no elapsed-time liquidation.

## Causal source-gap correction

The first run stopped before fitting because the public hourly archive had missing rows. The valid correction retained the full expected UTC grid, filled no missing price, and invalidated every feature or target whose required horizon crossed a gap.

| Symbol | Expected hours | Observed | Missing |
|---|---:|---:|---:|
| BTCUSDT | 19,728 | 19,184 | 544 |
| ETHUSDT | 19,728 | 19,384 | 344 |
| SOLUSDT | 19,728 | 19,245 | 483 |
| XRPUSDT | 19,728 | 19,565 | 163 |

No corrected model metric or PnL existed before this mechanical correction.

## Frozen model result

- Training rows: `24,612`
- Calibration rows: `17,664`
- Untouched confirmation rows: `17,376`
- Raw prediction mean: `−2.1578bp`
- Calibration target mean: `−0.5973bp`
- Frozen non-negative zero-intercept calibration scale: **`0.0`**

The calibrated prediction was therefore exactly zero throughout confirmation. This was not an arbitrary risk cap: the fixed calibrator found no positive transportable magnitude from the raw model score.

## Confirmation economics

- Prediction standard deviation: `0bp`
- Spearman: undefined because the prediction was constant
- MAE: `43.4227bp`
- Constant baseline MAE: `43.4062bp`
- MAE skill: `−0.00038082`
- RMSE skill: `−0.00013393`
- Trades at 12/18/24bp: `0 / 0 / 0`
- Total return at 12/18/24bp: `0 / 0 / 0`
- Confirmation gate: **FAIL**
- Development opened: **no**
- Risk/leverage search opened: **no**
- 2024–2026 opened: **no**
- Orders: none

Every economic and predictive gate except non-ruin failed. Because no positive base expectancy existed, risk fractions from 0.25% to 60% and notional caps from 1x to 100x remained unopened.

## Reproducibility

- Successful workflow: `30201775655`
- Artifact: `8631893147`
- Artifact digest: `sha256:ac4141ad10478f93725f563e65c808131ff1e4da310d0d77b0422d9958ca9b33`
- Artifact `RESULT.json`: `fdb6f39ee1ef7b7c91c998dbd58b2b79c31a22712a991442a961f3d4823f16e5`
- `MODEL_FIT.json`: `7d711628e943a126b6fbc840ed314755b90f738d80eed99d9ecb387551ed631e`
- `CONFIRMATION.json`: `d6974177b3eb8361b374db34ff99ba32d4dca566143c4412c2749358a1cfaa5c`
- `MODEL_CONTRACT.json`: `28509fa23a7a4f71200d6249d2106ef8da9276887b41ce8e657463ab881993e0`
- `SOURCE_MANIFEST.json`: `af4325457cf35c7dcb99c261dedc6687749e8d80d20bb0b606062a6559af03d4`
- Corrected runner: `3b48d134f68e656dbb111716c334a654655ebaa1de763fc660177a0c0029ac3a`
- Pytest: six passed
- Self-test: passed

## Decision

Retire this exact direct hourly utility formulation. Do not flip the calibration sign after observing the result, relax the non-negative scale, tune HGBT parameters, add features, change target horizon, lower turnover cost, alter the structural stop, or rescue it with risk and leverage. The next route must introduce materially different cost-sized predictive information or a different payoff, not a cosmetic model variant.
