# Sources and mechanism boundary

## Market data

- Official Bybit public MetaTrader 4 kline archive: `https://public.bybit.com/kline_for_metatrader4/`.
- Native five-minute BTCUSDT, ETHUSDT, SOLUSDT and XRPUSDT monthly gzip files are read on complete UTC grids. Every downloaded file is CRC-read and SHA-256 recorded.

## Economic mechanism

The SMC/ICT vocabulary is used only as a readable state description:

- accumulation = a completed frozen 30-minute range;
- manipulation = a completed one-sided boundary raid and reclaim;
- distribution = delivery toward the untouched boundary after the third-third open.

No hidden dealer intent, unobserved order book or retrospective swing label enters the model. The model uses completed prices and volume only. External technical-level microstructure research motivates the general idea that visible price levels can host clustered conditional orders, but no published profitability claim is accepted as project evidence.
