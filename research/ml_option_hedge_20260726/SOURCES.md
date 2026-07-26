# Source contract

Only public Tardis first-day-monthly datasets are used.

- `deribit/trades/YYYY/MM/DD/OPTIONS.csv.gz`: option aggressor transactions.
- `bybit/quotes/YYYY/MM/DD/BTCUSDT.csv.gz`: executable BTCUSDT BBO, structural pools and account fills.
- `bybit/quotes/YYYY/MM/DD/ETHUSDT.csv.gz`: executable ETHUSDT BBO, structural pools and account fills.

The availability clock is the exchange timestamp plus conservative cross-provider delay. Deribit and Bybit `local_timestamp` values are never compared across collection regions. Every file receives a full GZIP read, SHA-256, byte count, row count and monotonicity check.

The earlier fixed-rule option-flow claim is reused only as source/schema evidence. Its damaged strategy-source transport and all fixed-rule logic are excluded.
