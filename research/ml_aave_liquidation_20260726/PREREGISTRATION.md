# Aave on-chain liquidation burst → ETH liquidity first passage

## Claim and deliberate reduction

- Claim: `CLM-20260726-1952-ML-AAVE-LIQUIDATION-001`.
- One external information unit: finalized Ethereum Aave V2/V3 `LiquidationCall` logs.
- One model: one fixed pooled `HistGradientBoostingClassifier`.
- One action: one cost-adjusted `LONG`, `SHORT`, or `FLAT` first-passage equation.
- One traded instrument: `ETHUSDT` USDT-linear perpetual; one global pending/open slot.
- No model, feature, event-window, threshold, target, stop, risk, leverage, asset, side, or cost grid.

Aave liquidations are actual protocol state transitions: a liquidator repays debt and receives collateral. This is not a relabeling of CEX liquidation messages, inferred vulnerable inventory, open-interest changes, funding, ordinary taker flow, or price lead-lag.

## Phase 0 — outcome-sealed source gate

The address source is pinned to official `aave-dao/aave-address-book` release `4.61.2`, commit `4ae19b95f84b077c28633ca1d0f9a6750a3ea1d4`. The canonical event signature is frozen as:

```solidity
event LiquidationCall(
  address indexed collateralAsset,
  address indexed debtAsset,
  address indexed user,
  uint256 debtToCover,
  uint256 liquidatedCollateralAmount,
  address liquidator,
  bool receiveAToken
);
```

The probe may call only keyless Ethereum mainnet JSON-RPC methods needed to verify transport and logs: `eth_chainId`, `eth_blockNumber`, `eth_getCode`, `eth_getBlockByNumber`, and `eth_getLogs`. It opens no ETH price, future return, first-passage label, action, trade, PnL, model metric, official project period, credential, or order path.

Frozen probe dates are UTC days chosen before observing event counts:

- 2021-05-19;
- 2021-12-04;
- 2022-05-12;
- 2022-06-13;
- 2022-11-09;
- 2023-03-11;
- 2023-08-17.

The source gate passes only if all are true:

1. one keyless endpoint reports Ethereum chain ID 1 and nonempty bytecode at both canonical pool addresses;
2. every returned log decodes under the frozen ABI and its address equals the queried pool;
3. at least four of seven dates contain one or more liquidation logs and total decoded logs are at least 25;
4. block timestamps are retrievable for every event block and the evidence artifact preserves the raw logs, canonical addresses, endpoint, hashes, and date/block ranges.

A failure closes this source route without opening outcomes. A pass authorizes exactly the frozen history/model stage below.

## Historical source and availability

The conditional history stage reads all Aave V2/V3 `LiquidationCall` logs from `2021-01-01 00:00:00 UTC` through `2023-12-31 23:59:59 UTC` using adaptive non-overlapping block ranges. Every log is keyed by `(blockHash, transactionHash, logIndex)`; duplicates are rejected.

A log is not information at its nominal block timestamp. Its availability time is conservatively frozen as:

```text
block_timestamp + 120 seconds
```

Logs are aggregated into completed UTC five-minute buckets by block timestamp. A bucket becomes usable only at `bucket_end + 120 seconds`. Reorg-aware live deployment would require finalized blocks; this historical screen deliberately uses the larger fixed delay because local receipt timestamps do not exist.

Token decimals and canonical asset categories are read from immutable contract metadata and the pinned Aave address book. Unknown assets remain in count and concentration features but contribute no invented USD amount. Stable debt is limited to canonical DAI/USDC/USDT-family assets. WETH/stETH/wstETH/rETH-family collateral uses the last completed ETHUSDT minute close; WBTC-family collateral uses the last completed BTCUSDT minute close. Prices are strictly earlier than the information time.

## Frozen event features

Every nonempty completed five-minute liquidation bucket receives exactly these fit-time standardized values:

1. `log1p(total_known_debt_usd)`;
2. `log1p(eth_family_collateral_usd)`;
3. `log1p(wbtc_family_collateral_usd)`;
4. crypto-collateral USD share of known liquidation value;
5. stable-debt USD share of known debt value;
6. liquidation event count;
7. unique liquidated borrower count;
8. borrower notional Herfindahl concentration;
9. unique liquidator count;
10. liquidator notional Herfindahl concentration;
11. fraction receiving underlying collateral rather than aTokens;
12. Aave V3 event share;
13. prior completed 15-minute ETH return;
14. prior completed 60-minute ETH realized volatility;
15. current bucket ETH return divided by prior completed 60-minute realized volatility;
16. upper structural-pool distance from entry;
17. lower structural-pool distance from entry.

No wallet identity skill score, later borrower outcome, future oracle state, future price, MFE, MAE, final first-passage result, backward-smoothed state, or post-decision liquidation log is a feature.

## Price map, label, and execution

The proxy price source is immutable Binance public `ETHUSDT` and `BTCUSDT` one-minute archives. It is used only for the pre-2024 fatal screen. A survivor must be replayed on exact Bybit BBO, market/mark/funding and executable quantity before ranking.

At each information time, prior completed 15-minute bars build confirmed swing highs and lows with two bars on each side. A pivot becomes known only after the second right-hand bar closes. A pivot consumed after confirmation is removed. The nearest still-unconsumed confirmed high above the next executable minute open and low below it, searched over the preceding 14 calendar days, are frozen external buy-side and sell-side liquidity pools. The event is ineligible unless both exist and each distance is at least 12 basis points.

The label is whichever frozen pool is touched first after entry. Same-minute dual touches are ambiguous and excluded from fitting. For account replay they are adverse-first. A source-boundary-unresolved position is charged as a full adverse structural loss plus cost; there is no elapsed-time liquidation.

Entry is the first available minute open after `bucket_end + 120 seconds`. It may never use a price from the event bucket or a favorable intra-minute price.

## Chronology and one fixed model

- fit: 2021-01-01 through 2022-06-30;
- calibration: 2022-07-01 through 2022-12-31;
- untouched confirmation: 2023-01-01 through 2023-06-30;
- conditional development: 2023-07-01 through 2023-12-31;
- official 2024-01-01 through 2026-06-30: code-prohibited until all pre-2024 gates pass.

The predictor is exactly:

```text
HistGradientBoostingClassifier(
  learning_rate=0.05,
  max_iter=120,
  max_leaf_nodes=7,
  min_samples_leaf=20,
  l2_regularization=1.0,
  random_state=20260726
)
```

Training-only medians impute missing numeric values. If calibration contains at least 50 resolved labels and both classes, one isotonic map is fitted; otherwise the raw HGBT probability is retained. This rule is frozen before outcomes.

The non-fitted comparison probability is structural distance only:

```text
p_up_baseline = lower_distance / (upper_distance + lower_distance)
```

## One action rule and account path

For model probability `p_up`, entry-relative pool distances, and round-trip modeled cost:

```text
EV_LONG  = p_up * upper_distance - (1-p_up) * lower_distance - cost
EV_SHORT = (1-p_up) * lower_distance - p_up * upper_distance - cost
```

Choose the larger positive value; otherwise remain flat. The identical chronological signal is replayed at 12, 18, and 24 basis points. One pending/open ETH position blocks every later event. Base planned structural-loss risk is 0.5% of NAV with a fixed 3x notional cap. Risk and leverage are not search dimensions.

## Gates

The confirmation stage must satisfy every item before development PnL is opened:

1. at least 50 resolved confirmation labels and both classes;
2. model ROC AUC above the distance baseline;
3. positive Brier skill relative to the distance baseline;
4. at least 30 completed global-slot trades at 18 bp;
5. positive return in both chronological confirmation halves at 18 bp;
6. profit factor at least 1.10 at 18 bp;
7. non-negative return at 24 bp;
8. positive 18 bp return after removing the top five winners and the top 10% positive winners;
9. top-five positive-PnL share no greater than 35%;
10. no forced liquidation or irrecoverable account path.

Conditional 2023H2 development must independently meet the same economic/concentration gates. Passing only authorizes an unchanged exact-Bybit reconstruction and official walk-forward; it grants no rank or order permission.

Failure retires this exact Aave-liquidation-bucket → ETH structural first-passage dependency. Results may not be rescued by more RPC endpoints, different bucket sizes, selected crash dates, wallet ranking, event thresholds, adjacent assets, model changes, target/stop changes, or leverage.
