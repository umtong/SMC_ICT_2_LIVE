# Preregistration — ML XRPL exchange-inventory inflow

## Claim

`CLM-20260726-2305-ML-XRPL-INFLOW-001`

The information unit is finalized native-XRP inventory movement into frozen labeled exchange accounts. It is economically distinct from completed-bar seasonality, price-only structure, funding/open-interest inference, liquidation prints and the closed XRPL DEX OHLC transport dependency.

The causal hypothesis is not that every deposit is a sale. The hypothesis is that the amount, breadth, concentration and exchange distribution of completed deposits create a measurable inventory-pressure state that can improve a cost-adjusted structural first-passage decision on Bybit XRPUSDT.

## Phase 1: outcome-sealed official-source gate

Phase 1 may open only:

- the five frozen exchange account identities below;
- official public XRPL full-history JSON-RPC responses from `ledger_index`, `account_info` and ledger-index-bounded `account_tx`;
- five frozen 24-hour dates ending before 2024;
- immutable response bodies, hashes and parser diagnostics.

Phase 1 must not open Bybit prices, returns, future labels, a fitted model, strategy PnL, an official 2024–2026 market outcome, credentials or orders.

### Frozen accounts

| Exchange | Role | XRPL account |
|---|---|---|
| Binance | legacy deposit | `rEb8TK3gBgk5auZkwc6sHnwrGVJH8DuaLh` |
| Binance | current deposit/hot wallet | `rNxp4h8apvRis6mJf9Sh8C6iRxfrDWN7AV` |
| Bitstamp | deposit/hot wallet | `rDsbeomae4FXwgQTJp9Rs64Qg9vDiTCdBv` |
| Bybit | legacy deposit | `rJn2zAPdFA193sixJwuFixRkYDUtx3apQh` |
| Bybit | current deposit/hot wallet | `rMvCasZ9cohYrSZRNYPTZfoaaSUQMfgQ8G` |

The frozen account set is also the internal-transfer exclusion set. A qualifying customer-like inflow must come from outside this set and include a destination tag. Untagged and exchange-to-exchange movements remain separately counted but cannot satisfy the primary density gate.

### Frozen source dates

- 2021-05-05 00:00:00 through 2021-05-06 00:00:00 UTC
- 2022-01-12 00:00:00 through 2022-01-13 00:00:00 UTC
- 2022-11-09 00:00:00 through 2022-11-10 00:00:00 UTC
- 2023-06-07 00:00:00 through 2023-06-08 00:00:00 UTC
- 2023-11-08 00:00:00 through 2023-11-09 00:00:00 UTC

`ledger_index` maps each timestamp to a validated ledger boundary. `account_tx` is then requested with fixed minimum and maximum ledger indexes, oldest-first order, stable-marker pagination and JSON transaction bodies. The parser retains only validated successful `Payment` transactions whose destination equals the queried account and whose delivered asset is native XRP.

### Source pass rule

All of the following must hold:

1. every frozen date has validated start and end ledger boundaries;
2. no account/date query terminates at a page cap or unresolved marker;
3. at least four dates contain at least 25 external tagged inflows and at least 10 positive 15-minute bins;
4. total external tagged inflows are at least 500;
5. at least 100 distinct external source accounts appear;
6. at least 150 exchange/date/15-minute positive bins appear;
7. Binance, Bitstamp and Bybit each contribute at least 25 external tagged inflows and appear on at least three frozen dates.

A pass opens the frozen pre-2024 ML stage. A failure closes this exact account set/source dependency before any market outcome is inspected.

## Phase 2 contract, opened only after a source pass

### Event clock and information availability

- Aggregate validated source transactions into completed UTC 15-minute bins.
- A source bin is not usable until the later of its final included ledger close and a frozen 30-second processing delay.
- Entry cannot occur before the first Bybit executable price after that availability time.
- All rolling baselines, quantiles and normalization are prior-only.

### Features

The fixed feature families are:

- external tagged inflow XRP and transaction count over 15 minutes, 1 hour and 4 hours;
- distinct sender count and repeated-sender share;
- largest-transfer and top-three concentration;
- Binance, Bitstamp and Bybit family shares and cross-exchange breadth;
- exchange-to-exchange and untagged shares as contamination controls;
- prior-only inflow z-scores and percentile ranks;
- contemporaneous completed Bybit structural state: distance to pre-known prior-day and causally confirmed 4-hour external liquidity, completed volatility, displacement efficiency and funding state.

No future price extremum, later-confirmed pivot, future fill, MFE/MAE or realized label may enter a feature.

### Model and action

- One pooled histogram gradient boosting classifier plus one frozen probability calibration rule.
- It estimates structural downside-target-first versus upside-target-first probability after costs.
- LONG, SHORT or FLAT is selected by a single frozen expected-value comparison at 24 bp primary all-in cost.
- There is no model zoo and no feature-subset, target, stop, threshold, leverage or risk grid.

### Position and exit

- Product: Bybit `XRPUSDT` USDT linear perpetual.
- One global pending/open position slot.
- Entry: first executable Bybit price after the completed source/market state becomes available.
- Stop and target: frozen before entry at the nearest opposing and directional pre-known external-liquidity levels, with a fixed minimum 2.5R target eligibility rule.
- Exit: target, stop, failed structural acceptance, or an opposite completed inventory/market transition. There is no elapsed-time forced liquidation.
- Same-bar ambiguity is adverse: stop first unless finer executable data establish the sequence.

### Chronological development and official progression

- 2021 through 2022H1: train.
- 2022H2: probability calibration.
- 2023H1: untouched confirmation.
- 2023H2: frozen development/account-path confirmation.
- System structure, features, retraining rule, threshold, execution, sizing and cost contract must be frozen by 2023-12-31 before 2024H1 opens.
- A pre-2024 survivor must be positive at 24 bp, positive after exact top-10%-positive-event removal with full slot rerouting, trade-broad and not dependent on one exchange/date. Weak alpha is not rescued by leverage.
- If the pre-2024 gate passes, 2024H1 opens immediately and is recorded as seen thereafter.

## Reproducibility

Every RPC response is stored with request payload, endpoint, status, byte count and SHA-256. Account pages are represented by ordered response-hash roots, exact markers and parsed event hashes. The workflow uploads an immutable artifact even when the source gate fails.
