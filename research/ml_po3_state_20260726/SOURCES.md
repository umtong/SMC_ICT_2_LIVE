# Sources and causal availability

- Binance Vision monthly USD-M 5-minute kline archives and adjacent published CHECKSUM files. A candle is usable only after its close.
- Binance Vision monthly fundingRate archives and adjacent CHECKSUM files. A rate is applied only at its recorded `calc_time`.
- The official archives are an initial proxy because their complete pre-2024 public history is reproducible. A survivor cannot be ranked or open the official 2024 interval before an exact Bybit replay.
- Model motivation: stationary order-flow-derived variables are used instead of raw price levels; the implementation itself remains the frozen causal contract.
