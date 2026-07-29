# Spot-led intermarket SMT Core takeover

This fatal screen tests whether a completed Binance spot external-liquidity acceptance contains a cost-surviving Bybit perpetual delivery opportunity after a conservative two-second cross-provider source delay and the fixed 500ms order latency.

The workflow reuses immutable Bybit artifact `8626087323` and downloads only Tardis public first-day Binance spot trades for `2022-07-01` and `2023-07-01`. Provider `local_timestamp` values are never compared across venues.

```bash
python -m pytest -q research/ml_spotled_smt_core/test_semantics.py
python research/ml_spotled_smt_core/run.py \
  --spot-2022 BTCUSDT_trades_2022-07-01.csv.gz \
  --spot-2023 BTCUSDT_trades_2023-07-01.csv.gz \
  --bybit-2022 2022-07-01_BTCUSDT_state.parquet \
  --bybit-2023 2023-07-01_BTCUSDT_state.parquet \
  --output artifact
```

No credentials or orders are used. A negative, sparse, sub-cost or baseline-inferior result retires this exact information unit without delay, pivot, model, cost, risk or leverage rescue.
