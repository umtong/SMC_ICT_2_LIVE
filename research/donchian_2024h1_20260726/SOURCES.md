# Sources

- Bybit public MT4 kline archive: `https://public.bybit.com/kline_for_metatrader4/<SYMBOL>/<YEAR>/<FILE>.csv.gz`
- Bybit V5 linear kline fallback: `/v5/market/kline`, interval `60`
- Bybit V5 historical funding: `/v5/market/funding/history`

The exact downloaded URL, byte size and SHA-256 are recorded in `bar_transport.json`, `funding_status.json` and the result source manifest. December 2023 is warm-up only. No 2024H2 or later URL is requested.
