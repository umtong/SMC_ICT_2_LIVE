# Minimal ML BitMEX liquidation relay

This claim tests one point-in-time information source rather than another completed-candle trading template.

## SMC/ICT explanation

A BitMEX `XBTUSD` forced-liquidation burst is a mechanical liquidity raid. After the burst is causally closed and a conservative transport delay has elapsed, the model asks one question: will Bybit `BTCUSDT` accept the displacement and deliver to same-side external liquidity, or reject/reclaim it and deliver to opposing liquidity?

The two Bybit liquidity destinations are frozen from information available before the burst. They are also the only target and stop. The model does not invent another order block, FVG, session, entry pattern or target family.

## Minimal system

- one `HistGradientBoostingClassifier`;
- one frozen isotonic calibration map;
- ten normalized, trader-readable features;
- one upper-versus-lower first-passage label;
- one cost-adjusted LONG/SHORT/FLAT equation;
- one Bybit BTCUSDT slot;
- no model, feature, threshold, risk or leverage search.

## Causal boundary

- BitMEX liquidation rows are grouped until a fixed two-second quiet interval completes.
- The decision waits another five seconds.
- Entry uses the first Bybit BBO at least one further second later.
- Same-interval dual touches are never favorable.
- A source-boundary position pays its full structural stop.
- 2023 opens only after every 2022 confirmation gate passes.
- Every 2024–2026 source is prohibited in code.

## Reproduction

The tracked source is compressed to reduce repository transport. CI reconstructs it and refuses to run unless SHA-256 is exactly:

```text
89bf545c4edfbdde2743f150a9128c5e1da35854d5877723bbd3a6d785bfb606
```

Then run:

```bash
python bitmex_liq_ml.py --self-test
python bitmex_liq_ml.py --output /tmp/result --cache /tmp/tardis-cache
```

The initial output is a sparse, non-rank-eligible fatal information screen. A survivor still requires continuous Bybit replay, actual funding and broader capacity evidence.
