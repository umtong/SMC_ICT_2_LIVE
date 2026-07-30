# Transcript-grounded SMC/ICT ML system

This package implements one coherent SMC/ICT family rather than a collection
of independent indicators or named patterns.

## Core market hypothesis

A directional opportunity is eligible only when all four events are present in
causal order:

1. **A known liquidity pool exists.** The pool must be a prior UTC-day
   high/low, a causally confirmed swing, a confirmed equal-high/equal-low
   cluster, or a completed dealing-range boundary.
2. **Price sweeps and reclaims that pool.** Merely touching an order block or
   fair-value gap is not a signal.
3. **Displacement closes through internal structure.** Body/range expansion,
   close location, volume/regime, and cross-asset behavior describe the quality
   of the move; the close through the pre-sweep internal level supplies the
   market-structure shift.
4. **An opposing-liquidity objective supports valid trade geometry.** The stop
   sits beyond the swept extreme. The objective is the nearest valid opposing
   pool, with an ATR fallback only when no completed external level exists.

Fair-value gaps and the last opposing candle are execution locations after the
sequence above. They never create standalone entries. Time-of-day, conventional
indicators, open interest, account ratios, funding, premium/basis, volatility,
and BTC/ETH relative behavior are ML state features, not hard-coded buy/sell
rules.

## ML role

A gradient-boosted regression model estimates cost-net `R` for deterministic,
SMC-valid candidates. It is not allowed to generate arbitrary trades. The
small structural grid varies confirmation strictness around the same market
hypothesis and is selected on 2023H2 only. The final model is refit using only
outcomes resolved before 2024-01-01 and is frozen for the first 2024H1 causal
run.

## Execution and account contract

- Bybit USDT linear perpetuals; BTCUSDT and ETHUSDT in the first run.
- One global slot includes both a pending entry and an open position.
- Completed 5-minute bars generate signals. New orders activate 500 ms later.
  With one-minute execution data, the first permissible market fill is the next
  fully observable minute, never the signal bar's close or a favorable
  same-bar price.
- A retracement limit order requires penetration beyond its price. It cancels
  only if the swept structure is invalidated or the opposing objective is
  delivered without a fill. There is no timeout cancellation.
- Positions exit only at the stop or opposing-liquidity objective. There is no
  forced time exit. An open position at an evaluation boundary is marked to a
  conservative immediate-close value.
- A minute containing both stop and target is scored as stop first.
- Sizing uses current account NAV and the complete per-unit stop loss including
  fees, baseline slippage, and estimated impact. The simulator chooses the
  lowest leverage that both supplies margin and leaves the adverse stop beyond
  the approximate liquidation level. Any forced liquidation invalidates the
  account path.
- UTC daily NAV includes every calendar day. Funding is applied only when the
  position is open at the recorded funding timestamp.

The current Bybit non-VIP perpetual/futures fee schedule used by the code is
`0.0550%` taker and `0.0200%` maker. The exchange notes that actual regional or
account rates may differ, so deployment must replace the defaults with the
account's live fee rate. Funding is `position value × funding rate`, with
positive funding paid by longs to shorts.

Official references:

- https://www.bybit.com/en/help-center/article/Trading-Fee-Structure
- https://www.bybit.com/en/help-center/article/Funding-fee-calculation/
- https://www.bybit.com/en/help-center/article/Types-of-Orders-Available-on-Bybit

## Causal preparation and evaluation

```text
2021-01-01 .. 2023-06-30  model training outcomes
2023-07-01 .. 2023-12-31  structural/threshold/risk calibration
2023-12-31 23:59:59 UTC   preparation boundary
2024-01-01 .. 2024-06-30  first causal evaluation
```

Candidates whose trade outcome is unresolved at a preparation cutoff are not
used as model labels. The evaluation account starts at 10,000 USDT and is never
reset inside the interval.

## Run

```bash
python -m pip install numpy pandas pyarrow scikit-learn joblib
python research/youtube_smc_ict_ml/run_research.py \
  --data-root canonical_data \
  --output artifacts/youtube_smc_ict_ml
```

The GitHub workflow pins and reuses the canonical Bybit data builder rather
than introducing another market-data contract. Outputs include the selected
policy, model, candidates, trades, daily NAV, cost stress, feature importance,
and SHA-256 artifact manifest.
