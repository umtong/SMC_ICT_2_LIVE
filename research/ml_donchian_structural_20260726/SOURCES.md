# Sources and retained rationale

## Market and funding data

- Bybit public MT4 kline archive root: `https://public.bybit.com/kline_for_metatrader4/`
- BTCUSDT, ETHUSDT, SOLUSDT and XRPUSDT hourly USDT-linear contract archives.
- Bybit V5 public funding-history endpoint when it returns sufficient historical coverage.
- If historical funding is incomplete, every expected eight-hour boundary receives a fixed adverse 2 bp reserve; missing funding is never treated as zero.

Every downloaded archive is recorded by URL, byte size and SHA-256. The expected UTC hourly grid is retained. Missing price rows are invalid, reset every rolling feature and label horizon, and may never be interpolated or forward-filled.

## Model rationale

One `HistGradientBoostingRegressor` is used because the frozen information unit is a medium-sized tabular dataset with nonlinear interactions among displacement, trend efficiency, cross-asset breadth, residual return, volatility, volume and funding state. No alternative model or feature grid is opened.

The benchmark is not a generic accuracy baseline. It is the matched unfiltered Donchian all-breakout account under the same Bybit source, structural stop/channel exit, global slot, funding treatment and 24 bp cost path.

## Structural lineage

The fixed entry/exit geometry is inherited from `RES-20260726-DONCHIAN-DEPENDENCE-001`, but the previous after-winner/after-loser dependence filters are not reused. The materially new information unit is a pooled causal ML estimate of the completed structural trade's 24 bp net return. Channel lengths, stop, exit and trading universe are not searched.
