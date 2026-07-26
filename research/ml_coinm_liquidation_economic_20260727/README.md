# COIN-M forced-liquidation flow → Bybit structural-delivery ML

This is the conditional economic continuation of parent claim `CLM-20260726-2020-ML-BINANCE-LIQ-DENSE-001`, not a second strategy family.

## Trader-readable mechanism

1. Completed Binance COIN-M BTC/ETH forced liquidations reveal an actual transfer of vulnerable leveraged inventory.
2. Prior-only liquidation magnitude, side concentration, cross-asset breadth and contemporaneous completed price impact distinguish cascade continuation from exhaustion.
3. Already-confirmed, unconsumed Bybit BTCUSDT/ETHUSDT 15-minute external-liquidity pools freeze the upper and lower first-passage paths.
4. One pooled HGBT estimates upper-pool-first probability.
5. One cost-adjusted equation selects LONG, SHORT or FLAT for the single global Bybit slot.
6. Positions end at the frozen target or structural stop. No elapsed-time exit exists.

COIN-M contract counts are not hardcoded into unsupported dollar notionals. Magnitude features use prior-only within-symbol standardization. COIN-M is signal-only; account PnL is measured on Bybit USDT-linear BTCUSDT/ETHUSDT.

## Minimal causal sequence

- fit: 2021-01-01 through 2022-06-30;
- calibration: 2022H2;
- untouched confirmation: 2023H1;
- conditional development and broad risk/cap selection: 2023H2;
- freeze at 2023-12-31;
- immediately open official 2024H1.

Confirmation and development open the next stage when the 24bp account is positive and avoids liquidation or irrecoverable NAV loss. AUC, Brier skill, trade count, median, PF, concentration and winner removal remain diagnostics rather than extra purity gates.

## Fixed model and action

`HistGradientBoostingClassifier(learning_rate=0.05, max_iter=120, max_leaf_nodes=7, min_samples_leaf=20, l2_regularization=1.0, random_state=20260727)` plus one predetermined isotonic map when calibration has at least 50 resolved observations and both classes.

At the first executable minute open after the completed liquidation minute plus five seconds:

```text
EV_LONG  = p_up * upper_distance - (1-p_up) * lower_distance - all_in_cost
EV_SHORT = (1-p_up) * lower_distance - p_up * upper_distance - all_in_cost
```

The larger strictly positive action wins; otherwise FLAT. BTC and ETH compete for one slot.

## Account and risk

- identical 12/18/24bp paths;
- 0.5% planned structural-loss risk and 3x cap for the initial edge measurement;
- only after positive 24bp confirmation and development: 0.25%-60% risk and 1x-100x cap search;
- select the highest positive no-liquidation 24bp growth path; do not cap performance at 1%;
- actual Bybit funding when sufficiently complete, otherwise adverse 1bp per 8h for both sides;
- same-minute ambiguity is stop-first; adverse gaps fill at the open;
- exact top-winner event removal occurs before slot competition and the account is rerun as a diagnostic.

The workflow is intentionally dormant until the parent source PASS is known. No credentials or orders are used.
