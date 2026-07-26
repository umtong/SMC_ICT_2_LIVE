# Uniswap WETH–stablecoin inventory transfer → ETHUSDT hedge relay

Claim: `CLM-20260726-2110-ML-UNISWAP-HEDGE-TRANSFER-001`  
Branch: `agent/r14-ml-uniswap-hedge-transfer-001`

## One economic mechanism

A Uniswap V3 `Swap` event records the actual token-balance deltas of a pool. In a WETH–USDC or WETH–USDT pool, a large stablecoin inflow and WETH outflow is an actual WETH purchase; the opposite sign is an actual WETH sale. This is a completed inventory transfer, not an inferred chart setup, CEX liquidation message, funding threshold, open-interest estimate or ordinary CEX trade-print relabeling.

The testable mechanism is:

1. a large completed on-chain WETH inventory transfer occurs across canonical Uniswap V3 WETH–stablecoin pools;
2. arbitrageurs and market makers must rebalance or hedge the resulting inventory against centralized venues;
3. after a conservative information delay, one ML model estimates whether ETHUSDT reaches the already-known upper or lower external-liquidity pool first;
4. one cost-adjusted account equation chooses long, short or flat;
5. the frozen external-liquidity pools are the target and structural stop, so elapsed time never liquidates a position.

## Phase 0 — outcome-sealed source gate

The source gate may call only Ethereum mainnet JSON-RPC methods needed to verify and retrieve source data:

- `eth_chainId`;
- `eth_blockNumber`;
- `eth_getCode`;
- `eth_call` against the canonical Uniswap V3 factory and returned pools;
- `eth_getBlockByNumber`;
- `eth_getLogs`.

It may not open any CEX or DEX price comparison, future return, first-passage label, action, trade, PnL, model metric, official 2024–2026 period, credential or order path.

Pinned chain objects:

- Uniswap V3 factory: `0x1F98431c8aD98523631AE4a59f267346ea31F984`;
- WETH: `0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2`;
- USDC: `0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48`;
- USDT: `0xdAC17F958D2ee523a2206206994597C13D831ec7`;
- fee tiers: 500 and 3000;
- event: `Swap(address,address,int256,int256,uint160,uint128,int24)`;
- event topic: `0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67`.

The factory resolves each pool with `getPool(address,address,uint24)`. The probe then verifies pool bytecode and the immutable `token0`, `token1` and `fee` values before reading logs.

Frozen one-hour UTC probe windows, selected before counts are observed:

- `2021-05-19 12:00–13:00`;
- `2021-12-04 12:00–13:00`;
- `2022-05-12 12:00–13:00`;
- `2022-11-09 12:00–13:00`;
- `2023-03-11 12:00–13:00`;
- `2023-08-17 12:00–13:00`.

The source gate passes only if all are true:

1. one keyless endpoint reports Ethereum chain ID 1, nonempty factory/token bytecode and at least two correctly resolved pools;
2. every returned log has the frozen topic, queried pool address and decodes exactly into the frozen Swap ABI;
3. `(blockHash, transactionHash, logIndex)` identities contain no duplicates;
4. at least four frozen windows contain at least ten decoded swaps;
5. total decoded swaps are at least 100;
6. every decoded log has a retrievable block timestamp and zero decode errors.

Failure closes this route before outcomes. Passage opens exactly the fixed pre-2024 history and model stage below; it grants no ranking or order permission.

## Conditional history and information availability

Only after source passage, retrieve canonical pool Swap logs from `2021-05-05 00:00:00 UTC` through `2023-12-31 23:59:59 UTC` using adaptive, non-overlapping block ranges. Every record is keyed by `(blockHash, transactionHash, logIndex)` and duplicates are fatal.

Historical information availability is conservatively:

```text
block_timestamp + 120 seconds
```

Swaps are aggregated by block timestamp into completed UTC five-minute buckets. A bucket becomes usable only at `bucket_end + 120 seconds`. No event is backdated to transaction submission, nominal bucket start or an earlier CEX timestamp.

Stablecoin amounts use immutable six-decimal USDC/USDT units. Pool token ordering and amount signs determine whether stablecoin entered the pool and WETH left it, or the reverse. Unknown pool/token combinations are rejected rather than guessed.

## Frozen event definition

For each completed five-minute bucket, sum stablecoin notional and signed WETH direction across the four pinned pools. The fit partition alone determines the absolute-notional threshold as the larger of:

- 5,000,000 USDT-equivalent; or
- the fit partition's 99.5th percentile of nonzero five-minute absolute stablecoin notional.

A bucket is eligible only when:

- absolute stablecoin notional meets that single threshold;
- absolute directional stablecoin imbalance is at least 70%;
- at least two transactions contribute;
- the next executable ETHUSDT minute has both a frozen upper and lower external-liquidity pool at least 12 basis points away.

There is no threshold, event-window, asset, side or payoff grid.

## Frozen model features

One row contains exactly these causal values known by the decision time:

1. `log1p(total stablecoin notional)`;
2. signed stablecoin-to-WETH imbalance;
3. fraction of gross notional aligned with the net direction;
4. number of contributing swaps;
5. number of unique transactions;
6. transaction-notional Herfindahl concentration;
7. fraction of notional in the 500-fee pools;
8. cross-pool direction consensus;
9. weighted first-to-last Uniswap tick displacement within the bucket;
10. prior completed 15-minute ETHUSDT return;
11. prior completed 60-minute ETHUSDT realized volatility;
12. upper and lower frozen structural-pool distances, represented as two separate values.

The resulting model input has 13 numeric columns because the final structural-distance item contributes two distances. No future return, future DEX/CEX basis, MFE, MAE, eventual pool hit, wallet identity skill, later transaction, smoothed state or post-decision price enters a feature.

## Price proxy, label and execution

The pre-2024 fatal screen uses immutable Binance `ETHUSDT` one-minute archives as a price proxy. A survivor must be replayed on exact Bybit BBO, mark, funding, executable quantity and latency before it can rank.

At each information time, prior completed 15-minute bars form confirmed swing highs and lows with two bars on each side. A pivot becomes known only after the second right-hand bar closes. The nearest still-unconsumed confirmed high above the first executable minute open and confirmed low below it, searched over the preceding 14 calendar days, are frozen before entry.

The label is which frozen pool is touched first. A same-minute dual touch is excluded from fitting and treated stop-first in account replay. If the source ends while a position is open, the account receives the full adverse structural loss plus exit cost. No elapsed-time liquidation exists.

Entry is the first minute open strictly after `bucket_end + 120 seconds`. It may not use the event bucket close, same-block CEX state, a favorable intra-minute price or any earlier timestamp.

## One fixed ML system

Chronology:

- fit: `2021-05-05` through `2022-06-30`;
- calibration: `2022-07-01` through `2022-12-31`;
- untouched confirmation: `2023-01-01` through `2023-06-30`;
- conditional development: `2023-07-01` through `2023-12-31`;
- official `2024-01-01` through `2026-06-30`: prohibited until all pre-2024 gates pass.

Predictor:

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

Training-only medians impute missing numeric features. If calibration contains at least 50 resolved labels and both classes, fit one isotonic calibration map; otherwise retain the raw HGBT probability. No other model, feature subset, class weight, seed or hyperparameter is tried.

The non-fitted comparison probability is structural distance only:

```text
p_up_baseline = lower_distance / (upper_distance + lower_distance)
```

## One action equation and account path

For calibrated `p_up`, upper distance `u`, lower distance `d` and modeled round-trip cost `c`:

```text
EV_LONG  = p_up*u - (1-p_up)*d - c
EV_SHORT = (1-p_up)*d - p_up*u - c
```

Choose the larger strictly positive value; otherwise remain flat. One pending/open ETHUSDT position blocks every later event. The same chronological decisions are replayed at 12, 18 and 24 basis points. Base planned structural-loss risk is 0.5% NAV with a fixed 3x notional cap. Risk and leverage are not search dimensions in this route.

## Gates

Untouched confirmation must satisfy every item before development PnL is opened:

1. at least 50 resolved confirmation labels and both classes;
2. model ROC AUC exceeds the distance baseline;
3. positive Brier skill versus the distance baseline;
4. at least 30 completed one-slot trades at 18 bps;
5. positive return in both chronological confirmation halves at 18 bps;
6. profit factor at least 1.10 at 18 bps;
7. non-negative return at 24 bps;
8. positive 18-bps return after removing the largest positive 10% of event keys and fully rerouting the account;
9. no liquidation and maximum drawdown below 35%.

Conditional development must then satisfy all:

- positive full-period return at 24 bps;
- positive return in both 2023H2 quarters at 18 bps;
- positive median completed trade at 18 bps;
- at least 40 completed trades at 18 bps;
- positive winner-removed return at 18 bps;
- 18-bps maximum drawdown below 30%;
- 24-bps geometric daily growth strictly above the current recorded Donchian all-breakout benchmark `0.07001887213879954%` per UTC calendar day.

Failure retires the exact information unit without feature, threshold, cost, risk, leverage or model rescue. Passage authorizes an unchanged exact-Bybit reconstruction; it does not authorize orders.

## Source authorities

- official Uniswap V3 core repository and `IUniswapV3PoolEvents.sol` for the Swap ABI;
- official Uniswap V3 core factory/pool interfaces for `getPool`, `token0`, `token1` and `fee`;
- Ethereum JSON-RPC specification for `eth_getLogs`, `eth_getBlockByNumber`, `eth_getCode` and `eth_call`.

No credentials, paper orders, testnet orders or live orders are used.
