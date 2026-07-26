# Korean KRW Relative-Flow Lead into XRPUSDT

This directory freezes the pre-2024 fatal-alpha screen for
`CLM-20260726-1616-KRW-RELATIVE-001`.

## Economic mechanism

The signal is not the raw Kimchi premium. It removes two large common factors:

```text
local relative  = log(Upbit KRW-XRP close) - log(Upbit KRW-BTC close)
global relative = log(XRPUSDT close)        - log(BTCUSDT close)
regional basis  = local relative - global relative
```

Dividing XRP by BTC removes the KRW numeraire from the Korean leg and removes
most broad-crypto movement from both legs. The remaining state asks whether
Korean XRP-specific demand, accompanied by unusual KRW notional participation,
has moved through completed relative liquidity while the global XRP/BTC market
has not confirmed.

SMC/ICT translation:

1. Korean XRP/BTC accepts beyond completed external relative liquidity while
   global XRP/BTC refuses to confirm: intermarket SMT plus a regional leader;
2. or the preceding Korean relative close moves beyond its frozen pool and the
   next completed close returns inside while global liquidity remains intact:
   a close-defined liquidity raid and rejection;
3. require completed global displacement in the expected direction;
4. enter XRPUSDT at the following minute open;
5. stop beyond the frozen XRPUSDT structural swing;
6. exit at regional-basis closure, opposing global relative liquidity, or
   completed leader invalidation.

## Why relative liquidity uses closes only

A ratio high formed as `XRP high / BTC low` can combine two prices that never
coexisted inside a one-minute bar. This screen therefore never uses synthetic
cross-instrument OHLC highs or lows. Every local/global relative pool,
acceptance, sweep and reclaim is defined from completed relative closes. The
self-test mutates all Upbit high/low values and requires every relative signal to
remain unchanged.

## Frozen research boundary

- signal data: public Upbit `KRW-XRP` and `KRW-BTC` one-minute candles;
- execution proxy: official Binance Vision USD-M `XRPUSDT` and `BTCUSDT`
  one-minute bars;
- intended live market: Bybit linear `XRPUSDT` perpetual;
- 2022 fit; one exact survivor may open 2023 development;
- hard code prohibition on every timestamp at or after 2024-01-01 UTC;
- 192 fixed policies, one global position slot, next-open entry;
- structural price/state exits only—no elapsed-time liquidation;
- 12/18/24 bp all-in round-trip cost replays and a conservative adverse funding
  charge at every crossed UTC eight-hour boundary;
- no rule, risk or leverage rescue after failure;
- no credentials and no orders.

The initial output is intentionally non-rank-eligible because Binance bars are
only an execution proxy. An economic survivor must later be reconstructed with
exact Bybit executable quotes/depth and pass the official causal evaluation.

## Source reconstruction

`krw_relative.py.zlib.b64` is the zlib-compressed, Base64-encoded source. CI
rejects execution unless the decompressed SHA-256 is exactly:

```text
3dd9c0037adc68459acefe4c1d0a912f5e1832a48ebddf662d2bb80a514aaee1
```

Local reconstruction:

```bash
python - <<'PY'
import base64, zlib
from pathlib import Path
encoded = Path('krw_relative.py.zlib.b64').read_text().strip()
Path('krw_relative.py').write_bytes(zlib.decompress(base64.b64decode(encoded)))
PY
python krw_relative.py --self-test
python krw_relative.py --output ./result --cache ./cache
```

The exact data, timing, feature, policy, execution, selection and advancement
contracts are in `preregistration.json`.
