# GMX V1 Arbitrum liquidation → Bybit forced-flow relay

Claim: `CLM-20260726-2324-ML-GMX-V1-LIQUIDATION-001`  
Branch: `agent/r20-ml-gmx-v1-liquidation-001`

## One economic mechanism

The canonical GMX V1 Arbitrum Vault emits `LiquidatePosition` only after a position is actually liquidated. A liquidated long mechanically represents forced sell pressure in its index asset; a liquidated short represents forced buy pressure. This completed on-chain deleveraging event is distinct from a CEX liquidation message, inferred funding/open-interest state, Hyperliquid ledger update, Aave collateral seizure, ordinary trade print or completed-bar chart setup.

The testable mechanism is:

1. a finalized GMX V1 BTC or ETH position is force-closed on Arbitrum;
2. the liquidator, liquidity pool and cross-venue market makers absorb and hedge the resulting directional inventory;
3. after a conservative 120-second information delay, one ML model estimates continuation, exhaustion reversal or flat between already-known Bybit external-liquidity pools;
4. one cost-adjusted rule controls the single global BTC/ETH slot;
5. the frozen external-liquidity pools own target and invalidation, so elapsed time never liquidates a position.

## Phase 0 — outcome-sealed source gate

The source gate may call only Arbitrum JSON-RPC methods required to verify and retrieve source data:

- `eth_chainId`;
- `eth_blockNumber`;
- `eth_getCode`;
- `eth_getBlockByNumber`;
- `eth_getLogs`.

It may not open a CEX or DEX market price, future return, first-passage label, model metric, action, trade, PnL, account NAV, official 2024–2026 period, credential or order.

Pinned source identity:

- chain: Arbitrum One, chain ID `42161`;
- GMX V1 Vault: `0x489ee077994B6658eAfA855C308275EAd8097C4A`;
- event: `LiquidatePosition(bytes32,address,address,address,bool,uint256,uint256,uint256,int256,uint256)`;
- topic0: `0x2e1f85a64a2f22cf2f0c42584e7c919ed4abe8d53675cff0f62bf1e95a1c676f`;
- WBTC index token: `0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f`;
- WETH index token: `0x82aF49447D8a07e3bd95BD0d56f35241523fBab1`;
- record identity: `(blockHash, transactionHash, logIndex)`;
- causal availability: `block_timestamp + 120 seconds`.

Frozen half-open UTC windows, selected before counts are observed:

- `2021-12-01` through `2021-12-08`;
- `2022-05-08` through `2022-05-15`;
- `2022-06-10` through `2022-06-18`;
- `2022-11-06` through `2022-11-13`;
- `2023-03-08` through `2023-03-15`;
- `2023-08-14` through `2023-08-21`.

The gate passes only if all are true:

1. a keyless endpoint reports chain ID 42161, nonempty canonical Vault bytecode and usable historical block/log access;
2. every returned record has the frozen Vault and topic and decodes exactly into ten 32-byte ABI words;
3. decode errors, removed logs and duplicate identities are all zero;
4. at least 20 BTC/ETH liquidations exist;
5. at least four frozen windows contain BTC/ETH liquidations;
6. both BTC and ETH and both liquidated position sides are present;
7. every decoded record has a block timestamp and a delayed causal-availability timestamp.

Failure closes the route before outcomes. Passage opens exactly the frozen pre-2024 history and model stage below; it grants no ranking or order permission.

## Conditional full history and event state

Only after source passage, retrieve the same canonical event from `2021-07-01 00:00:00 UTC` through `2023-12-31 23:59:59 UTC`. Every event becomes usable only at `block_timestamp + 120 seconds`.

Events are aggregated into completed five-minute source states without backdating. The fit partition alone freezes an event threshold as the larger of:

- USD 250,000 liquidated notional; or
- the fit partition's 95th percentile of nonzero five-minute BTC/ETH liquidated notional.

An eligible state requires at least one event, at least 70% directional notional alignment, and both a pre-known upper and lower Bybit structural pool at least 18 basis points from the first executable price. There is no event-window, asset, side, threshold or payoff grid.

## Frozen causal features

One row contains only values known by decision time:

1. `log1p(total liquidated USD notional)`;
2. signed forced-flow notional, long liquidations negative and short liquidations positive;
3. directional-notional consensus;
4. liquidation count;
5. unique account count;
6. account-notional Herfindahl concentration;
7. BTC fraction of notional;
8. weighted liquidation mark-price dispersion;
9. prior completed 15-minute Bybit return;
10. prior completed 60-minute Bybit realized volatility;
11. prior completed funding rate;
12. upper frozen structural-pool distance;
13. lower frozen structural-pool distance.

No future return, later liquidation, MFE, MAE, eventual pool hit, post-decision price or later market state enters a feature.

## Frozen ML system

Chronology:

- fit: `2021-07-01` through `2022-06-30`;
- calibration: `2022-07-01` through `2022-12-31`;
- untouched confirmation: `2023-01-01` through `2023-06-30`;
- conditional development: `2023-07-01` through `2023-12-31`;
- official `2024-01-01` through `2026-06-30`: sealed until all pre-2024 gates pass.

Predictor:

```text
HistGradientBoostingClassifier(
  learning_rate=0.05,
  max_iter=160,
  max_leaf_nodes=7,
  min_samples_leaf=20,
  l2_regularization=1.0,
  random_state=20260726
)
```

Training-only medians impute missing numeric values. If calibration has at least 50 resolved labels and both classes, one isotonic map calibrates target-first probability; otherwise raw HGBT probabilities remain. No other model, feature subset, class weight, seed or hyperparameter is tried.

The non-fitted comparator is structural distance:

```text
p_up_baseline = lower_distance / (upper_distance + lower_distance)
```

The label is upper-pool-first versus lower-pool-first. A same-bucket dual touch is excluded from fitting and stop-first in replay. Source-end unresolved positions receive the full adverse structural loss plus exit cost. There is no elapsed-time liquidation.

## Action and account path

At the delayed decision time, compute continuation and reversal probabilities relative to the signed forced-flow direction. For each admissible long or short path with target distance `t`, stop distance `s` and modeled round-trip cost `c`:

```text
EV = p_target*t - (1-p_target)*s - c
```

Take the side with the largest strictly positive EV; otherwise stay flat. The first executable Bybit price strictly after information availability is used. One pending/open BTC or ETH position blocks every later event. Identical chronological decisions are replayed at 12, 18 and 24 basis points with actual funding and adverse same-bucket ordering. Base structural-loss risk is 0.5% NAV and the fatal-screen notional cap is 3x.

Untouched confirmation must have at least 40 resolved labels, both classes, model ROC AUC above the distance baseline, positive Brier skill, at least 30 one-slot trades at 18 bps, positive return in both chronological halves at 18 bps, PF at least 1.10, nonnegative 24-bp return, positive exact top-10% winner-removal rerouting, no liquidation and MDD below 35%.

Conditional 2023H2 development must be positive at 24 bps, positive in both quarters at 18 bps, have a positive median trade, at least 40 trades, positive exact winner-removal, MDD below 30%, and growth above the then-current valid rank-one hurdle.

Failure retires this exact information unit without adjacent feature, threshold, cost, risk, leverage or model rescue.

## Sequential official evaluation

A survivor is reconstructed on exact Bybit prices, funding, spread, latency, capacity, margin and continuous NAV. Pre-2024 information may then select the highest-growth no-liquidation risk/notional path from the project's preregistered search contract, conditional on positive exact winner-removal. The system is frozen through `2023-12-31` and official 2024H1 opens immediately.

Structurally distant 2024H1 performance retires the route and changes alpha. A promising result advances with information through each half-year cutoff to 2026H1. An already inspected interval may guide the next version but cannot be called fresh independent OOS after modification.

## Source authorities

- official GMX V1 `Vault.sol` for the exact `LiquidatePosition` ABI and emission point;
- archived official GMX V1 contract-address documentation for the Arbitrum Vault;
- Arbitrum JSON-RPC for chain, bytecode, block timestamp and log evidence.

No credentials, paper orders, testnet orders or live orders are used.
