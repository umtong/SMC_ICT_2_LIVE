# Sources

The scientific runner downloads only official Binance Vision USD-M daily five-minute kline ZIP archives:

`https://data.binance.vision/data/futures/um/daily/klines/{SYMBOL}/5m/{SYMBOL}-5m-{YYYY-MM-DD}.zip`

Each retained ZIP is integrity-tested, SHA-256 identified and listed in the output source manifest. Target days require all 288 bars. Breadth contracts are included only when at least 95% complete, and the event clock requires at least 16 contemporaneously valid non-target contracts. Missing prices are never imputed.

The initial stage is a Binance execution proxy. It cannot enter the cumulative ranking until a survivor receives unchanged Bybit BBO/depth, funding, latency, capacity and continuous-account validation.
